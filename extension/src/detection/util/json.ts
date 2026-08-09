/**
 * Tolerant JSON handling plus the generic "find the product in this blob"
 * search.
 *
 * Single-page stores ship their entire product model to the browser as JSON —
 * `__NEXT_DATA__`, `__PRELOADED_STATE__`, `dataLayer`, and a dozen bespoke
 * globals. We do not know the shape of any of them, and we never will for the
 * long tail of stores. So instead of per-store paths we walk the object graph
 * and score nodes on how much they look like a product.
 */

import { toAmount } from '../../lib/price';
import { cleanText } from '../../lib/text';

/** Hard limits so a pathological page can never lock up the popup. */
const MAX_NODES = 25_000;
const MAX_DEPTH = 14;
const MAX_JSON_CHARS = 4_000_000;

export type Json = unknown;

/**
 * Parse JSON that may be wrapped in JavaScript. Handles the common cases:
 * `window.__STATE__ = {...};`, a trailing semicolon, a leading `JSON.parse(`,
 * and HTML comment fences left over from old templating engines.
 */
export function safeJsonParse(raw: string | null | undefined): Json | undefined {
  if (!raw) return undefined;
  let text = raw.trim();
  if (!text || text.length > MAX_JSON_CHARS) return undefined;

  text = text
    .replace(/^<!--/, '')
    .replace(/-->$/, '')
    .trim();

  try {
    return JSON.parse(text);
  } catch {
    // Fall through to the salvage attempts below.
  }

  // `window.foo = {...};` / `var foo = {...}` — keep the object literal only.
  const assignment = text.match(/=\s*([[{][\s\S]*?[\]}])\s*;?\s*$/);
  if (assignment) {
    try {
      return JSON.parse(assignment[1]);
    } catch {
      /* keep trying */
    }
  }

  // JSON.parse("…") with an escaped string payload.
  const wrapped = text.match(/JSON\.parse\(\s*(["'])([\s\S]*?)\1\s*\)/);
  if (wrapped) {
    try {
      return JSON.parse(JSON.parse(`"${wrapped[2].replace(/"/g, '\\"')}"`));
    } catch {
      /* keep trying */
    }
  }

  // Trailing commas are the single most common hand-written-JSON-LD mistake.
  try {
    return JSON.parse(text.replace(/,\s*([}\]])/g, '$1'));
  } catch {
    return undefined;
  }
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Case-insensitive, snake/camel-insensitive property lookup. */
export function pick(node: Record<string, unknown>, aliases: string[]): unknown {
  const normalised = new Map<string, unknown>();
  for (const [key, value] of Object.entries(node)) {
    normalised.set(key.toLowerCase().replace(/[_\-\s]/g, ''), value);
  }
  for (const alias of aliases) {
    const value = normalised.get(alias.toLowerCase().replace(/[_\-\s]/g, ''));
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return undefined;
}

/**
 * Read a money value that may be one level deeper than expected.
 *
 * Stores routinely nest prices: `price: { mrp: 2299, discounted: 1149 }`. A
 * flat lookup finds an object and gives up, so when that happens we look inside
 * it with the same alias list.
 */
export function amountIn(node: Record<string, unknown>, keys: string[], nested?: string[]): number | undefined {
  const raw = pick(node, keys);
  const direct = toAmount(raw);
  if (direct !== undefined) return direct;
  if (isObject(raw)) return toAmount(pick(raw, nested ?? keys));
  return undefined;
}

export const KEYS = {
  name: [
    'name',
    'title',
    'productName',
    'productTitle',
    'displayName',
    'productDisplayName',
    'itemName',
    'item_name',
    'heading',
  ],
  brand: ['brand', 'brandName', 'manufacturer', 'vendor', 'item_brand', 'brandDetails'],
  price: [
    'price',
    'salePrice',
    'sellingPrice',
    'finalPrice',
    'discounted',
    'discountedPrice',
    'currentPrice',
    'offerPrice',
    'specialPrice',
    'unitPrice',
    'priceValue',
    'amount',
    'value',
  ],
  originalPrice: [
    'mrp',
    'listPrice',
    'originalPrice',
    'strikedPrice',
    'strikeOffPrice',
    'regularPrice',
    'wasPrice',
    'compareAtPrice',
    'maxPrice',
    'basePrice',
    'oldPrice',
  ],
  currency: ['currency', 'currencyCode', 'priceCurrency', 'currencySymbol'],
  sku: ['sku', 'skuId', 'styleId', 'itemId', 'item_id', 'productId', 'productCode', 'code', 'partNumber', 'id'],
  image: ['image', 'imageUrl', 'images', 'thumbnail', 'primaryImage', 'defaultImage', 'media', 'imageURL', 'src'],
  category: ['category', 'categoryName', 'productType', 'item_category', 'articleType', 'masterCategory'],
  variants: ['sizes', 'variants', 'skus', 'options', 'articles', 'variations', 'sizeOptions', 'swatches', 'shades'],
  availability: [
    'availability',
    'inStock',
    'isAvailable',
    'available',
    'stockStatus',
    'inventoryStatus',
    'isInStock',
    'sellable',
  ],
  quantity: ['quantity', 'stock', 'inventory', 'availableQuantity', 'sellableQuantity', 'stockCount', 'availableCount'],
  outOfStock: ['outOfStock', 'isOutOfStock', 'soldOut', 'isSoldOut'],
  variantLabel: ['size', 'name', 'label', 'value', 'title', 'displayName', 'sizeName', 'skuSize', 'shade', 'color'],
} as const;

/**
 * Breadth-first walk with hard caps. Returns every plain object encountered,
 * which is what the product scorer needs.
 */
export function collectNodes(root: Json): Array<Record<string, unknown>> {
  const nodes: Array<Record<string, unknown>> = [];
  const seen = new Set<object>();
  const queue: Array<{ value: Json; depth: number }> = [{ value: root, depth: 0 }];

  while (queue.length && nodes.length < MAX_NODES) {
    const { value, depth } = queue.shift()!;
    if (depth > MAX_DEPTH) continue;

    if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === 'object' && item !== null) queue.push({ value: item, depth: depth + 1 });
      }
      continue;
    }

    if (!isObject(value)) continue;
    if (seen.has(value)) continue; // cycles
    seen.add(value);
    nodes.push(value);

    for (const child of Object.values(value)) {
      if (typeof child === 'object' && child !== null) queue.push({ value: child, depth: depth + 1 });
    }
  }

  return nodes;
}

function plausibleName(value: unknown): string | undefined {
  const text = cleanText(value);
  if (!text) return undefined;
  if (text.length < 3 || text.length > 200) return undefined;
  if (/^https?:\/\//i.test(text)) return undefined;
  return text;
}

/**
 * How strongly a node smells like a product. A name alone is worth little
 * (every menu item has one); a name *next to* a price is the real signal.
 */
export function scoreProductNode(node: Record<string, unknown>): number {
  let score = 0;

  const name = plausibleName(pick(node, [...KEYS.name]));
  if (name) score += 2;

  const price = amountIn(node, [...KEYS.price]);
  if (price !== undefined) score += 3;

  if (name && price !== undefined) score += 2; // the combination is the signal

  if (pick(node, [...KEYS.brand]) !== undefined) score += 1;
  if (pick(node, [...KEYS.sku]) !== undefined) score += 1;
  if (pick(node, [...KEYS.image]) !== undefined) score += 1;
  if (amountIn(node, [...KEYS.originalPrice]) !== undefined) score += 1;

  const variants = pick(node, [...KEYS.variants]);
  if (Array.isArray(variants) && variants.length) score += 2;

  // Explicit self-identification, e.g. `{"@type":"Product"}` or `type:"product"`.
  const type = String(pick(node, ['@type', 'type', 'itemType']) ?? '').toLowerCase();
  if (type.includes('product')) score += 3;

  return score;
}

/** The highest-scoring product-like nodes in a blob, best first. */
export function findProductNodes(root: Json, limit = 5): Array<Record<string, unknown>> {
  return collectNodes(root)
    .map((node) => ({ node, score: scoreProductNode(node) }))
    .filter((entry) => entry.score >= 5)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((entry) => entry.node);
}

/** Flatten `{name}` / `["a","b"]` / `{"@id":…}` shapes down to a string. */
export function asString(value: unknown): string | undefined {
  if (typeof value === 'string') return cleanText(value);
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = asString(item);
      if (found) return found;
    }
    return undefined;
  }
  if (isObject(value)) {
    return asString(pick(value, ['name', 'value', 'title', 'label', '@id', 'text']));
  }
  return undefined;
}

/** Collect image URLs out of the many shapes stores use for them. */
export function asImageList(value: unknown, depth = 0): string[] {
  if (depth > 4) return [];
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap((item) => asImageList(item, depth + 1));
  if (isObject(value)) {
    const direct = pick(value, ['url', 'contentUrl', 'src', 'imageUrl', 'image', 'large', 'zoom', 'default']);
    if (direct !== undefined) return asImageList(direct, depth + 1);
  }
  return [];
}
