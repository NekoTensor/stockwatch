/**
 * Layer 4 — ordinary meta tags, Twitter cards, and the document title.
 *
 * The weakest structured layer, and the reason it exists: on a page with no
 * JSON-LD, no microdata and no OpenGraph, `<title>` plus `rel=canonical` is
 * still enough to name the product and give the backend a stable URL to poll.
 */

import { parsePrice } from '../../lib/price';
import { cleanText, stripSiteSuffix } from '../../lib/text';
import type { Candidate, DetectionContext } from '../../lib/types';
import { metaContent, queryAll } from '../util/dom';
import { identifyStore } from '../../stores/registry';

function meta(doc: Document, ...names: string[]): string | undefined {
  const selectors = names.flatMap((name) => [
    `meta[name="${name}" i]`,
    `meta[property="${name}" i]`,
    `meta[itemprop="${name}" i]`,
  ]);
  return cleanText(metaContent(doc, selectors));
}

/**
 * Twitter's "app card" fields are a favourite hiding place for prices:
 * `twitter:label1 = Price`, `twitter:data1 = ₹12,990`.
 */
function twitterLabelledValue(doc: Document, matcher: RegExp): string | undefined {
  for (const index of [1, 2, 3, 4]) {
    const label = meta(doc, `twitter:label${index}`);
    if (label && matcher.test(label)) {
      const value = meta(doc, `twitter:data${index}`);
      if (value) return value;
    }
  }
  return undefined;
}

export function extractMetaTags(ctx: DetectionContext): Candidate | undefined {
  const { doc } = ctx;

  const canonical = queryAll(doc, 'link[rel="canonical" i]')
    .map((el) => cleanText(el.getAttribute('href')))
    .find(Boolean);

  const store = identifyStore(ctx.hostname);
  const rawTitle = meta(doc, 'twitter:title') ?? cleanText(doc.title);
  const productName = rawTitle
    ? stripSiteSuffix(rawTitle, [store.name, store.domain, store.domain.split('.')[0]])
    : undefined;

  const priceText = twitterLabelledValue(doc, /price|mrp|cost/i) ?? meta(doc, 'price', 'product:price');
  const parsed = priceText ? parsePrice(priceText) : undefined;

  const image = meta(doc, 'twitter:image', 'twitter:image:src', 'thumbnail', 'image');

  if (!productName && !parsed && !image) return undefined;

  return {
    source: 'meta',
    confidence: 0.45,
    data: {
      productName,
      description: meta(doc, 'twitter:description', 'description'),
      canonicalUrl: canonical,
      // Deliberately *not* falling back to og:site_name: on a marketplace that
      // would report the brand of a Nike shoe as "Myntra".
      brand: meta(doc, 'brand', 'product:brand'),
      imageUrl: image,
      images: image ? [image] : [],
      currentPrice: parsed?.amount,
      currency: parsed?.currency,
      availability: 'unknown',
    },
  };
}
