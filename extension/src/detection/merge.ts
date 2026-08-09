/**
 * Merging what the layers found.
 *
 * Each layer answers the same questions independently and they frequently
 * disagree — JSON-LD says the jacket costs 12,990 while the DOM shows the
 * discounted 9,990; JSON-LD lists every size while only the DOM knows which
 * ones are greyed out. Rather than letting one layer win outright, fields are
 * resolved individually by trust, and variants are merged so the best names
 * meet the best availability data.
 */

import { discountPercentage } from '../lib/price';
import { normaliseKey } from '../lib/text';
import type { Candidate, ProductData, SourceLayer, Variant } from '../lib/types';
import { mergeAvailability } from './util/availability';

/**
 * Trust order, following the detection priority in the design:
 * structured data first, rendered pixels last.
 */
const PRIORITY: Record<SourceLayer, number> = {
  jsonld: 100,
  microdata: 85,
  embedded: 80,
  opengraph: 70,
  dom: 40,
  // Below the DOM on purpose. This layer is mostly `<title>`, which is SEO copy
  // ("Buy X Online at Best Price | Store") — a rendered <h1> inside the product
  // area is a better answer whenever we have one.
  meta: 35,
  url: 30,
  adapter: 0, // applied separately — adapters fill gaps, they do not compete
};

/** Fields resolved by simple "highest-trust non-empty value wins". */
const SCALAR_FIELDS = [
  'productName',
  'brand',
  'description',
  'sku',
  'productId',
  'category',
  'canonicalUrl',
  'imageUrl',
  'currency',
  'currentPrice',
  'originalPrice',
] as const;

export interface MergeOutput {
  data: Partial<ProductData>;
  provenance: Partial<Record<keyof ProductData, SourceLayer>>;
  layersUsed: SourceLayer[];
}

function isEmpty(value: unknown): boolean {
  return value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0);
}

/**
 * Merge variant sets by name.
 *
 * The set with the best combination of size, trust and known availability
 * becomes the skeleton; the others are then used to fill in availability and
 * SKUs for matching names. This is exactly the Zara/H&M case: structured data
 * names the sizes, the DOM knows which buttons are struck through.
 */
export function mergeVariantSets(sets: Array<{ source: SourceLayer; variants: Variant[] }>): Variant[] {
  const populated = sets.filter((set) => set.variants.length > 0);
  if (!populated.length) return [];

  const scoreOf = (set: { source: SourceLayer; variants: Variant[] }) => {
    const known = set.variants.filter((v) => v.availability !== 'unknown').length;
    const knownRatio = known / set.variants.length;
    return PRIORITY[set.source] / 10 + set.variants.length + knownRatio * 6;
  };

  const primary = [...populated].sort((a, b) => scoreOf(b) - scoreOf(a))[0];
  const merged = primary.variants.map((variant) => ({ ...variant }));
  const index = new Map(merged.map((variant) => [normaliseKey(variant.name), variant]));

  for (const set of populated) {
    if (set === primary) continue;
    for (const variant of set.variants) {
      const target = index.get(normaliseKey(variant.name));
      if (!target) continue;

      // Availability is the field worth combining: whichever layer actually
      // knows wins, and a disagreement resolves optimistically.
      if (target.availability === 'unknown') {
        target.availability = variant.availability;
        if (variant.availability !== 'unknown') target.source = variant.source;
      } else if (variant.availability !== 'unknown') {
        target.availability = mergeAvailability(target.availability, variant.availability);
      }

      target.sku ??= variant.sku;
      target.price ??= variant.price;
      target.group ??= variant.group;
    }
  }

  return merged;
}

export function mergeCandidates(candidates: Candidate[]): MergeOutput {
  const ordered = [...candidates].sort(
    (a, b) => PRIORITY[b.source] + (b.confidence ?? 0) - (PRIORITY[a.source] + (a.confidence ?? 0)),
  );

  const data: Partial<ProductData> = {};
  const provenance: Partial<Record<keyof ProductData, SourceLayer>> = {};

  for (const field of SCALAR_FIELDS) {
    for (const candidate of ordered) {
      const value = candidate.data[field];
      if (isEmpty(value)) continue;
      (data as Record<string, unknown>)[field] = value;
      provenance[field] = candidate.source;
      break;
    }
  }

  // Images: union across layers, best-trust first, de-duplicated.
  const images: string[] = [];
  for (const candidate of ordered) {
    for (const url of candidate.data.images ?? []) {
      if (url && !images.includes(url)) images.push(url);
    }
  }
  if (images.length) {
    data.images = images.slice(0, 8);
    provenance.images = ordered.find((c) => c.data.images?.length)?.source;
    if (!data.imageUrl) {
      data.imageUrl = images[0];
      provenance.imageUrl = provenance.images;
    }
  }

  // Availability: the first layer with an actual opinion.
  for (const candidate of ordered) {
    const status = candidate.data.availability;
    if (status && status !== 'unknown') {
      data.availability = status;
      provenance.availability = candidate.source;
      break;
    }
  }
  data.availability ??= 'unknown';

  const variants = mergeVariantSets(
    ordered.map((candidate) => ({ source: candidate.source, variants: candidate.data.variants ?? [] })),
  );
  if (variants.length) {
    data.variants = variants;
    provenance.variants = variants[0]?.source;
  }

  // A "discount" where the original is below the current price is a mis-read,
  // not a bargain — drop it rather than showing a negative saving.
  if (data.originalPrice !== undefined && data.currentPrice !== undefined) {
    if (data.originalPrice <= data.currentPrice) {
      delete data.originalPrice;
      delete provenance.originalPrice;
    }
  }
  data.discountPercentage = discountPercentage(data.currentPrice, data.originalPrice);

  return {
    data,
    provenance,
    layersUsed: ordered.filter((c) => Object.values(c.data).some((v) => !isEmpty(v))).map((c) => c.source),
  };
}
