/**
 * The detection pipeline.
 *
 *   store identified
 *        -> every generic layer runs (independently, failure-isolated)
 *        -> results merged field-by-field by trust
 *        -> the store adapter fills any remaining gaps
 *        -> normalised into one ProductData
 *        -> scored, so the UI can tell "found it" from "this isn't a product"
 *
 * No step above knows the name of a single store. That is the contract.
 */

import { currencyFromHostname } from '../lib/price';
import { cleanText, normaliseKey } from '../lib/text';
import type {
  Candidate,
  DetectionContext,
  DetectionResult,
  ProductData,
  SourceLayer,
  Variant,
} from '../lib/types';
import { absoluteUrl, cleanUrl, looksLikeNonProductUrl, looksLikeProductUrl, productIdFromUrl } from '../lib/url';
import { identifyStore } from '../stores/registry';
import { registry } from '../adapters/registry';
import { extractDom, type DomSignals } from './layers/dom';
import { extractEmbedded } from './layers/embedded';
import { extractJsonLd } from './layers/jsonld';
import { extractMetaTags } from './layers/metatags';
import { extractMicrodata } from './layers/microdata';
import { extractOpenGraph, hasProductOgType } from './layers/opengraph';
import { mergeCandidates } from './merge';

/** One misbehaving layer must never cost us the other five. */
function runLayer(
  name: SourceLayer,
  fn: () => Candidate | undefined,
  warnings: string[],
): Candidate | undefined {
  try {
    return fn();
  } catch (error) {
    warnings.push(`${name} extraction failed: ${(error as Error).message}`);
    return undefined;
  }
}

interface Signals extends DomSignals {
  jsonld: boolean;
  microdata: boolean;
  embedded: boolean;
  ogProduct: boolean;
  urlPositive: boolean;
  urlNegative: boolean;
  adapterVerdict: boolean | undefined;
}

/**
 * Confidence that this page *is* a product page. Deliberately additive: no
 * single signal can carry a page on its own, and no single missing signal can
 * sink one. Weights are tuned so that "structured data + a price" clears the
 * bar, and "a heading and nothing else" does not.
 */
function scorePage(signals: Signals): number {
  let score = 0;

  if (signals.jsonld) score += 30;
  if (signals.microdata) score += 18;
  if (signals.ogProduct) score += 18;
  if (signals.embedded) score += 14;

  if (signals.hasTitle) score += 10;
  if (signals.hasPrice) score += 18;
  if (signals.hasVariants) score += 10;
  if (signals.hasBuyButton) score += 14;
  if (signals.hasBreadcrumb) score += 4;
  if (signals.hasGallery) score += 4;

  if (signals.urlPositive) score += 10;
  if (signals.urlNegative) score -= 25;

  // A repeated grid of priced, linked cards is a category page. Structured data
  // outweighs it, so a product page that happens to carry a "complete the look"
  // rail still clears the bar.
  if (signals.listingGrid) score -= 30;

  if (signals.adapterVerdict === true) score += 15;
  if (signals.adapterVerdict === false) score -= 30;

  return Math.max(0, Math.min(100, score));
}

function dedupeVariants(variants: Variant[]): Variant[] {
  const seen = new Set<string>();
  const out: Variant[] = [];
  for (const variant of variants) {
    const key = normaliseKey(variant.name);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(variant);
  }
  return out;
}

export function runDetection(ctx: DetectionContext): DetectionResult {
  const started = Date.now();
  const warnings: string[] = [];

  const store = identifyStore(ctx.hostname);
  const adapter = registry.resolve(ctx);

  const candidates: Candidate[] = [];
  const jsonld = runLayer('jsonld', () => extractJsonLd(ctx), warnings);
  const microdata = runLayer('microdata', () => extractMicrodata(ctx), warnings);
  const embedded = runLayer('embedded', () => extractEmbedded(ctx), warnings);
  const opengraph = runLayer('opengraph', () => extractOpenGraph(ctx), warnings);
  const metatags = runLayer('meta', () => extractMetaTags(ctx), warnings);

  let domResult: { candidate: Candidate; signals: DomSignals } | undefined;
  try {
    domResult = extractDom(ctx);
  } catch (error) {
    warnings.push(`dom extraction failed: ${(error as Error).message}`);
  }

  for (const candidate of [jsonld, microdata, embedded, opengraph, metatags, domResult?.candidate]) {
    if (candidate) candidates.push(candidate);
  }

  const merged = mergeCandidates(candidates);
  const data = merged.data;
  const provenance = { ...merged.provenance };

  // --- adapter pass: gaps only, unless the adapter declares itself authoritative
  try {
    const input = { ctx, base: data as Readonly<Partial<ProductData>> };
    const contributions: Array<Partial<ProductData>> = [];

    const product = adapter.detectProduct?.(input);
    if (product) contributions.push(product);

    const price = adapter.detectPrice?.(input);
    if (price) contributions.push(price);

    const availability = adapter.detectAvailability?.(input);
    if (availability && availability !== 'unknown') contributions.push({ availability });

    const variants = adapter.detectVariants?.(input);
    if (variants?.length) contributions.push({ variants });

    for (const contribution of contributions) {
      for (const [key, value] of Object.entries(contribution)) {
        if (value === undefined || value === null || value === '') continue;
        const field = key as keyof ProductData;
        const existing = (data as Record<string, unknown>)[field];
        const empty = existing === undefined || existing === '' || (Array.isArray(existing) && !existing.length);
        if (empty || adapter.authoritative) {
          (data as Record<string, unknown>)[field] = value;
          provenance[field] = 'adapter';
        }
      }
    }
  } catch (error) {
    warnings.push(`adapter "${adapter.id}" failed: ${(error as Error).message}`);
  }

  // --- normalisation
  const productUrl = cleanUrl(ctx.url);
  const images = (data.images ?? [])
    .map((url) => absoluteUrl(url, ctx.url))
    .filter((url): url is string => Boolean(url));

  const productId = data.productId ?? productIdFromUrl(ctx.url);
  if (!data.productId && productId) provenance.productId = 'url';

  const currency = data.currency ?? store.currency ?? currencyFromHostname(ctx.hostname);
  if (!data.currency && currency) provenance.currency = 'url';

  const variants = dedupeVariants(data.variants ?? []);

  const product: ProductData = {
    store: store.name,
    storeId: store.id,
    storeDomain: store.domain,
    productName: cleanText(data.productName),
    brand: cleanText(data.brand),
    productUrl,
    canonicalUrl: absoluteUrl(data.canonicalUrl, ctx.url),
    productId,
    sku: data.sku,
    imageUrl: absoluteUrl(data.imageUrl, ctx.url) ?? images[0],
    images,
    category: cleanText(data.category),
    description: data.description,
    currency,
    currentPrice: data.currentPrice,
    originalPrice: data.originalPrice,
    discountPercentage: data.discountPercentage,
    availability: data.availability ?? 'unknown',
    variants,
    detectedAt: new Date().toISOString(),
  };

  // --- scoring
  const adapterVerdict = adapter.isProductPage?.(ctx);
  const signals: Signals = {
    ...(domResult?.signals ?? {
      hasTitle: Boolean(product.productName),
      hasPrice: product.currentPrice !== undefined,
      hasBuyButton: false,
      hasVariants: variants.length > 0,
      hasBreadcrumb: false,
      hasGallery: false,
      listingGrid: false,
    }),
    hasTitle: Boolean(product.productName),
    hasPrice: product.currentPrice !== undefined,
    hasVariants: variants.length > 0,
    jsonld: Boolean(jsonld),
    microdata: Boolean(microdata),
    embedded: Boolean(embedded),
    ogProduct: hasProductOgType(ctx.doc),
    urlPositive: looksLikeProductUrl(ctx.url),
    urlNegative: looksLikeNonProductUrl(ctx.url),
    adapterVerdict,
  };
  const confidence = scorePage(signals);

  // --- what could we not read?
  const missing: string[] = [];
  if (!product.productName) missing.push('Product name');
  if (product.currentPrice === undefined) missing.push('Price');
  if (!product.imageUrl) missing.push('Product image');
  if (!variants.length) missing.push('Variants');
  if (!product.brand) missing.push('Brand');

  if (variants.length && variants.every((variant) => variant.availability === 'unknown')) {
    warnings.push('Variant availability could not be determined on this page.');
  }
  if (!variants.length && product.currentPrice !== undefined) {
    warnings.push('No variants found — this product can still be tracked for price.');
  }

  const hasCore = Boolean(product.productName) && (product.currentPrice !== undefined || variants.length > 0);

  let status: DetectionResult['status'];
  if (hasCore && confidence >= 55) status = 'detected';
  else if (product.productName && confidence >= 35) status = 'partial';
  else status = 'not_a_product';

  return {
    status,
    product: status === 'not_a_product' ? undefined : product,
    confidence,
    missing,
    warnings,
    provenance,
    layersUsed: merged.layersUsed,
    adapterId: adapter.id,
    durationMs: Date.now() - started,
  };
}
