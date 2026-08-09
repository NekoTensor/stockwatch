/**
 * Layer 1 — schema.org Product in `<script type="application/ld+json">`.
 *
 * This is the highest-trust layer and it is not a nice-to-have: Google Merchant
 * listings effectively require it, so a large share of real stores publish a
 * complete, machine-readable product right in the page. When it is present we
 * get the name, brand, SKU, image, price, currency, availability and often the
 * full variant matrix without touching a single CSS selector.
 */

import { toAmount } from '../../lib/price';
import { normaliseKey } from '../../lib/text';
import type { Candidate, DetectionContext, StockStatus, Variant, VariantType } from '../../lib/types';
import { availabilityFromSchema } from '../util/availability';
import { VARIANT_TOKEN, queryAll } from '../util/dom';
import { asImageList, asString, isObject, pick, safeJsonParse } from '../util/json';

const PRODUCT_TYPES = /(^|\/)(Product|ProductModel|ProductGroup|IndividualProduct|Vehicle|Book|SoftwareApplication)$/i;

function typesOf(node: Record<string, unknown>): string[] {
  const raw = node['@type'] ?? node.type;
  if (typeof raw === 'string') return [raw];
  if (Array.isArray(raw)) return raw.filter((t): t is string => typeof t === 'string');
  return [];
}

function isProductNode(node: unknown): node is Record<string, unknown> {
  return isObject(node) && typesOf(node).some((type) => PRODUCT_TYPES.test(type));
}

/** Flatten @graph, arrays and nested product references into one list. */
function flatten(root: unknown, depth = 0, out: Array<Record<string, unknown>> = []): Array<Record<string, unknown>> {
  if (depth > 6) return out;

  if (Array.isArray(root)) {
    for (const item of root) flatten(item, depth + 1, out);
    return out;
  }
  if (!isObject(root)) return out;

  out.push(root);

  for (const key of ['@graph', 'mainEntity', 'itemListElement', 'hasVariant', 'isVariantOf', 'item']) {
    if (root[key] !== undefined) flatten(root[key], depth + 1, out);
  }

  return out;
}

/** Offers arrive as one Offer, an array of Offers, or an AggregateOffer. */
function collectOffers(node: Record<string, unknown>): Array<Record<string, unknown>> {
  const raw = node.offers ?? node.offer;
  const list: Array<Record<string, unknown>> = [];

  const push = (value: unknown, depth = 0) => {
    if (depth > 3) return;
    if (Array.isArray(value)) {
      for (const item of value) push(item, depth + 1);
      return;
    }
    if (!isObject(value)) return;
    list.push(value);
    if (value.offers !== undefined) push(value.offers, depth + 1); // AggregateOffer
  };

  push(raw);
  return list;
}

function priceFromOffer(offer: Record<string, unknown>): number | undefined {
  const direct = toAmount(pick(offer, ['price', 'lowPrice', 'highPrice']));
  if (direct !== undefined) return direct;

  const spec = offer.priceSpecification;
  if (isObject(spec)) return toAmount(pick(spec, ['price', 'minPrice', 'maxPrice']));
  if (Array.isArray(spec)) {
    for (const item of spec) {
      if (isObject(item)) {
        const value = toAmount(pick(item, ['price', 'minPrice', 'maxPrice']));
        if (value !== undefined) return value;
      }
    }
  }
  return undefined;
}

function currencyFromOffer(offer: Record<string, unknown>): string | undefined {
  const direct = asString(pick(offer, ['priceCurrency', 'currency']));
  if (direct) return direct.toUpperCase();
  const spec = offer.priceSpecification;
  if (isObject(spec)) {
    const nested = asString(pick(spec, ['priceCurrency', 'currency']));
    if (nested) return nested.toUpperCase();
  }
  return undefined;
}

/**
 * Offer names are usually the variant itself ("M", "UK 8", "256GB") rather than
 * a labelled axis, so fall back to recognising the value's shape.
 */
function variantTypeFromLabel(label: string | undefined): VariantType {
  if (!label) return 'generic';
  const text = label.toLowerCase();
  if (/shade/.test(text)) return 'shade';
  if (/colou?r/.test(text)) return 'color';
  if (/size|fit/.test(text)) return 'size';
  if (/capacity|storage|memory/.test(text)) return 'capacity';
  if (/length/.test(text)) return 'length';
  if (/flavou?r|scent/.test(text)) return 'flavor';
  if (/style|model/.test(text)) return 'style';

  if (/^\d+\s?(gb|tb|mb)$/i.test(label)) return 'capacity';
  if (/^\d+\s?(ml|l|g|kg|oz)$/i.test(label)) return 'capacity';
  if (VARIANT_TOKEN.test(label)) return 'size';

  return 'generic';
}

/**
 * A product with several named offers is a variant matrix: each offer is a
 * size or shade with its own SKU, price and availability. This is the single
 * richest variant source on the web when a store bothers to publish it.
 */
function variantsFromOffers(offers: Array<Record<string, unknown>>): Variant[] {
  if (offers.length < 2) return [];

  const variants: Variant[] = [];
  const seen = new Set<string>();

  for (const offer of offers) {
    const label =
      asString(pick(offer, ['name', 'sku', 'gtin13', 'gtin', 'mpn'])) ??
      asString(isObject(offer.itemOffered) ? pick(offer.itemOffered, ['name', 'sku']) : undefined);
    if (!label) continue;

    const key = normaliseKey(label);
    if (!key || seen.has(key)) continue;
    seen.add(key);

    variants.push({
      id: asString(pick(offer, ['sku', '@id', 'mpn'])) ?? label,
      name: label,
      type: variantTypeFromLabel(label),
      availability: availabilityFromSchema(asString(pick(offer, ['availability', 'itemCondition']))),
      sku: asString(pick(offer, ['sku'])),
      price: priceFromOffer(offer),
      source: 'jsonld',
    });
  }

  // Offer names that are all SKUs rather than sizes are noise, not variants.
  const looksLikeLabels = variants.filter((v) => v.name.length <= 12).length >= variants.length / 2;
  return looksLikeLabels ? variants : [];
}

/** ProductGroup → hasVariant → Product[] is the modern, explicit encoding. */
function variantsFromGroup(node: Record<string, unknown>): Variant[] {
  const raw = node.hasVariant;
  if (!Array.isArray(raw)) return [];

  const variants: Variant[] = [];
  for (const item of raw) {
    if (!isObject(item)) continue;

    const axis =
      asString(pick(item, ['size', 'color', 'colour', 'pattern', 'material'])) ??
      asString(pick(item, ['name']));
    if (!axis) continue;

    const offers = collectOffers(item);
    variants.push({
      id: asString(pick(item, ['sku', 'productID', '@id'])) ?? axis,
      name: axis,
      type: item.size !== undefined ? 'size' : item.color !== undefined ? 'color' : 'generic',
      availability: offers.length
        ? availabilityFromSchema(asString(pick(offers[0], ['availability'])))
        : 'unknown',
      sku: asString(pick(item, ['sku'])),
      price: offers.length ? priceFromOffer(offers[0]) : undefined,
      source: 'jsonld',
    });
  }
  return variants;
}

/** Prefer the node that describes *this* page and carries the most detail. */
function scoreNode(node: Record<string, unknown>, url: string): number {
  let score = 0;
  if (asString(pick(node, ['name']))) score += 2;
  if (collectOffers(node).length) score += 3;
  if (pick(node, ['sku', 'productID', 'mpn']) !== undefined) score += 1;
  if (pick(node, ['image']) !== undefined) score += 1;
  if (pick(node, ['brand']) !== undefined) score += 1;
  if (Array.isArray(node.hasVariant)) score += 2;

  const nodeUrl = asString(pick(node, ['url', '@id']));
  if (nodeUrl && url.includes(nodeUrl.replace(/^https?:\/\/[^/]+/, ''))) score += 3;

  return score;
}

export function extractJsonLd(ctx: DetectionContext): Candidate | undefined {
  const blocks = queryAll(ctx.doc, 'script[type="application/ld+json"], script[type="application/json+ld"]');
  if (!blocks.length) return undefined;

  const products: Array<Record<string, unknown>> = [];
  for (const block of blocks) {
    const parsed = safeJsonParse(block.textContent);
    if (parsed === undefined) continue;
    for (const node of flatten(parsed)) {
      if (isProductNode(node)) products.push(node);
    }
  }
  if (!products.length) return undefined;

  const node = products.sort((a, b) => scoreNode(b, ctx.url) - scoreNode(a, ctx.url))[0];
  const offers = collectOffers(node);

  // The cheapest offer is what the shopper sees as "the price".
  const prices = offers.map(priceFromOffer).filter((p): p is number => p !== undefined);
  const currentPrice = prices.length ? Math.min(...prices) : undefined;
  const currency = offers.map(currencyFromOffer).find(Boolean);

  const listPrice = offers
    .map((offer) => {
      const spec = offer.priceSpecification;
      if (isObject(spec) && /list|strike|previous/i.test(String(spec['@type'] ?? ''))) {
        return toAmount(pick(spec, ['price']));
      }
      return toAmount(pick(offer, ['listPrice', 'highPrice', 'strikePrice']));
    })
    .find((value): value is number => value !== undefined);

  const availabilities = offers.map((offer) => availabilityFromSchema(asString(pick(offer, ['availability']))));
  const availability: StockStatus = availabilities.includes('in_stock')
    ? 'in_stock'
    : availabilities.includes('out_of_stock')
      ? 'out_of_stock'
      : 'unknown';

  const groupVariants = variantsFromGroup(node);
  const offerVariants = groupVariants.length ? [] : variantsFromOffers(offers);

  const images = asImageList(node.image).slice(0, 8);

  return {
    source: 'jsonld',
    confidence: 0.95,
    data: {
      productName: asString(pick(node, ['name'])),
      brand: asString(pick(node, ['brand', 'manufacturer'])),
      description: asString(pick(node, ['description'])),
      sku: asString(pick(node, ['sku', 'mpn'])),
      productId: asString(pick(node, ['productID', 'productId', 'gtin13', 'gtin', 'sku'])),
      category: asString(pick(node, ['category'])),
      canonicalUrl: asString(pick(node, ['url'])),
      imageUrl: images[0],
      images,
      currency,
      currentPrice,
      originalPrice: listPrice,
      availability,
      variants: groupVariants.length ? groupVariants : offerVariants,
    },
  };
}
