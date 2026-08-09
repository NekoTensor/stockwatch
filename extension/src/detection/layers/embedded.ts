/**
 * Layer 5 — embedded application state.
 *
 * Single-page storefronts ship their product model to the browser as JSON and
 * then render it with JavaScript: `__NEXT_DATA__`, `__PRELOADED_STATE__`,
 * `__NUXT__`, `dataLayer`, Tealium's `utag_data`, Apollo caches, and a long
 * tail of bespoke globals.
 *
 * We do not hard-code paths into any of them. Instead the blob is walked and
 * every object is scored on how much it looks like a product (see
 * `util/json.ts`). That is what lets an unknown boutique on Shopify or a
 * regional marketplace work on day one — they all ship a `{name, price, sizes}`
 * object somewhere, whatever they choose to call the wrapper.
 */

import { toAmount } from '../../lib/price';
import { cleanText, normaliseKey } from '../../lib/text';
import type { Candidate, DetectionContext, StockStatus, Variant, VariantType } from '../../lib/types';
import {
  availabilityFromFlag,
  availabilityFromNegativeFlag,
  mergeAvailability,
} from '../util/availability';
import { queryAll } from '../util/dom';
import {
  KEYS,
  amountIn,
  asImageList,
  asString,
  findProductNodes,
  isObject,
  pick,
  safeJsonParse,
} from '../util/json';

/** Inline `<script>` payloads worth parsing, cheapest checks first. */
function inlineBlobs(doc: Document): unknown[] {
  const blobs: unknown[] = [];

  // 1. Framework state that ships as a typed JSON script tag.
  for (const el of queryAll(
    doc,
    'script#__NEXT_DATA__, script[type="application/json"], script[id*="state" i][type*="json" i], script[data-testid*="state" i]',
  )) {
    const parsed = safeJsonParse(el.textContent);
    if (parsed !== undefined) blobs.push(parsed);
  }

  // 2. `window.__X__ = {...}` assignments inside plain scripts.
  const assignment =
    /(?:window|self|globalThis)\.(__[A-Z0-9_]+__|__[A-Za-z0-9_]+|[A-Za-z_$][\w$]*)\s*=\s*([[{])/;
  for (const el of queryAll(doc, 'script:not([src])')) {
    const text = el.textContent;
    if (!text || text.length < 40 || text.length > 3_000_000) continue;
    if (!assignment.test(text)) continue;

    const match = text.match(assignment);
    if (!match) continue;

    const start = text.indexOf(match[2], match.index ?? 0);
    const literal = extractBalanced(text, start);
    if (literal) {
      const parsed = safeJsonParse(literal);
      if (parsed !== undefined) blobs.push(parsed);
    }
  }

  return blobs;
}

/**
 * Pull one balanced `{...}` / `[...]` literal out of a larger script, keeping
 * track of strings so a brace inside a product description does not end it.
 */
function extractBalanced(text: string, start: number): string | undefined {
  const open = text[start];
  if (open !== '{' && open !== '[') return undefined;
  const close = open === '{' ? '}' : ']';

  let depth = 0;
  let inString: string | undefined;
  let escaped = false;

  for (let i = start; i < text.length; i += 1) {
    const ch = text[i];

    if (inString) {
      if (escaped) escaped = false;
      else if (ch === '\\') escaped = true;
      else if (ch === inString) inString = undefined;
      continue;
    }

    if (ch === '"' || ch === "'") {
      inString = ch;
      continue;
    }
    if (ch === open) depth += 1;
    else if (ch === close) {
      depth -= 1;
      if (depth === 0) return text.slice(start, i + 1);
    }

    if (i - start > 3_000_000) break; // safety valve
  }

  return undefined;
}

function variantTypeFrom(label: string, sample: string): VariantType {
  const hint = `${label} ${sample}`.toLowerCase();
  if (/shade/.test(hint)) return 'shade';
  if (/colou?r/.test(hint)) return 'color';
  if (/\b\d+\s?(gb|tb|mb)\b/.test(hint) || /capacity|storage/.test(hint)) return 'capacity';
  if (/\b\d+\s?(ml|l|g|kg|oz)\b/.test(hint) || /volume|weight/.test(hint)) return 'capacity';
  if (/length/.test(hint)) return 'length';
  if (/flavou?r|scent/.test(hint)) return 'flavor';
  if (/size|fit/.test(hint)) return 'size';
  return 'generic';
}

/** Read stock off a variant object, checking positive and negative phrasings. */
function variantAvailability(entry: Record<string, unknown>): StockStatus {
  let status = availabilityFromFlag(pick(entry, [...KEYS.availability]));
  status = mergeAvailability(status, availabilityFromFlag(pick(entry, [...KEYS.quantity])));

  const negative = pick(entry, [...KEYS.outOfStock]);
  if (negative !== undefined) status = mergeAvailability(status, availabilityFromNegativeFlag(negative));

  return status;
}

function variantsFromNode(node: Record<string, unknown>): Variant[] {
  const raw = pick(node, [...KEYS.variants]);
  if (!Array.isArray(raw) || !raw.length || raw.length > 200) return [];

  const groupLabel = Object.keys(node).find((key) => KEYS.variants.some((v) => v.toLowerCase() === key.toLowerCase())) ?? '';
  const variants: Variant[] = [];
  const seen = new Set<string>();

  for (const item of raw) {
    let label: string | undefined;
    let entry: Record<string, unknown> = {};

    if (typeof item === 'string' || typeof item === 'number') {
      label = cleanText(String(item));
    } else if (isObject(item)) {
      entry = item;
      label = asString(pick(item, [...KEYS.variantLabel]));
    }

    if (!label || label.length > 40) continue;
    const key = normaliseKey(label);
    if (!key || seen.has(key)) continue;
    seen.add(key);

    variants.push({
      id: asString(pick(entry, ['skuId', 'sku', 'id', 'code'])) ?? label,
      name: label,
      type: variantTypeFrom(groupLabel, label),
      availability: variantAvailability(entry),
      sku: asString(pick(entry, ['skuId', 'sku'])),
      price: toAmount(pick(entry, [...KEYS.price])),
      group: groupLabel || undefined,
      source: 'embedded',
    });
  }

  return variants;
}

function candidateFromNode(node: Record<string, unknown>): Candidate['data'] {
  const images = asImageList(pick(node, [...KEYS.image])).slice(0, 8);

  // `price` is as likely to be `{ mrp, discounted, currency }` as it is to be a
  // number, so the money fields are read one level deep as well as flat.
  const priceRaw = pick(node, [...KEYS.price]);
  const priceObject = isObject(priceRaw) ? priceRaw : undefined;

  const currentPrice = amountIn(node, [...KEYS.price]);
  const originalPrice =
    amountIn(node, [...KEYS.originalPrice]) ??
    (priceObject ? toAmount(pick(priceObject, [...KEYS.originalPrice])) : undefined);
  const currency =
    asString(pick(node, [...KEYS.currency])) ??
    (priceObject ? asString(pick(priceObject, [...KEYS.currency])) : undefined);

  return {
    productName: asString(pick(node, [...KEYS.name])),
    brand: asString(pick(node, [...KEYS.brand])),
    sku: asString(pick(node, ['sku', 'skuId', 'styleId'])),
    productId: asString(pick(node, [...KEYS.sku])),
    category: asString(pick(node, [...KEYS.category])),
    imageUrl: images[0],
    images,
    currency: currency && /^[A-Za-z]{3}$/.test(currency) ? currency.toUpperCase() : undefined,
    currentPrice,
    originalPrice,
    availability: variantAvailability(node),
    variants: variantsFromNode(node),
  };
}

export function extractEmbedded(ctx: DetectionContext): Candidate | undefined {
  const blobs: unknown[] = [...inlineBlobs(ctx.doc)];

  // Globals harvested from the page's MAIN world by the popup.
  for (const value of Object.values(ctx.pageGlobals)) {
    if (value !== undefined && value !== null) blobs.push(value);
  }
  if (!blobs.length) return undefined;

  const nodes = blobs.flatMap((blob) => findProductNodes(blob, 3));
  if (!nodes.length) return undefined;

  // Merge the best few candidates: stores often split the descriptive product
  // from its price object, and neither alone is complete.
  const merged: Candidate['data'] = {};
  let variants: Variant[] = [];

  for (const node of nodes.slice(0, 3)) {
    const data = candidateFromNode(node);
    for (const [key, value] of Object.entries(data) as Array<[keyof Candidate['data'], unknown]>) {
      if (key === 'variants' || key === 'images') continue;
      if (value === undefined || value === '' || value === 'unknown') continue;
      if (merged[key] === undefined) (merged as Record<string, unknown>)[key] = value;
    }
    if (data.images?.length && !merged.images?.length) merged.images = data.images;
    if (data.variants?.length && data.variants.length > variants.length) variants = data.variants;
  }

  if (!merged.productName && merged.currentPrice === undefined) return undefined;

  return {
    source: 'embedded',
    confidence: 0.75,
    data: { ...merged, variants },
  };
}
