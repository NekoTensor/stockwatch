/**
 * Layer 3 — OpenGraph and the `product:*` extensions.
 *
 * Every store that wants a decent preview when its links are pasted into
 * WhatsApp or Instagram maintains these tags, which makes them the most widely
 * present source of a product's name, image and price. They rarely describe
 * variants, so this layer fills the header of the card, not the size grid.
 */

import { parsePrice, toAmount } from '../../lib/price';
import { cleanText } from '../../lib/text';
import type { Candidate, DetectionContext } from '../../lib/types';
import { availabilityFromSchema } from '../util/availability';
import { metaContent, queryAll } from '../util/dom';

/** `property=` is the spec; `name=` is what half the web actually ships. */
function og(doc: Document, ...keys: string[]): string | undefined {
  const selectors = keys.flatMap((key) => [
    `meta[property="${key}" i]`,
    `meta[name="${key}" i]`,
  ]);
  return cleanText(metaContent(doc, selectors));
}

export function extractOpenGraph(ctx: DetectionContext): Candidate | undefined {
  const { doc } = ctx;

  const type = og(doc, 'og:type')?.toLowerCase() ?? '';
  const title = og(doc, 'og:title');
  const priceAmount = og(doc, 'product:price:amount', 'og:price:amount', 'product:sale_price:amount');
  const originalAmount = og(
    doc,
    'product:original_price:amount',
    'og:original_price:amount',
    'product:list_price:amount',
  );

  if (!title && !priceAmount) return undefined;

  const currency =
    og(doc, 'product:price:currency', 'og:price:currency', 'product:sale_price:currency')?.toUpperCase() ??
    (priceAmount ? parsePrice(priceAmount)?.currency : undefined);

  const images = queryAll(doc, 'meta[property="og:image" i], meta[property="og:image:secure_url" i], meta[name="og:image" i]')
    .map((el) => cleanText(el.getAttribute('content')))
    .filter((value): value is string => Boolean(value))
    .slice(0, 8);

  return {
    source: 'opengraph',
    // `og:type=product` is an explicit claim; without it these tags may just
    // be describing a category page, so the layer trusts itself less.
    confidence: /product|og:product/.test(type) ? 0.85 : 0.6,
    data: {
      productName: title,
      description: og(doc, 'og:description'),
      canonicalUrl: og(doc, 'og:url'),
      brand: og(doc, 'product:brand', 'og:brand', 'product:manufacturer'),
      category: og(doc, 'product:category', 'article:section'),
      productId: og(doc, 'product:retailer_item_id', 'product:item_group_id', 'og:sku'),
      sku: og(doc, 'product:retailer_item_id', 'og:sku'),
      imageUrl: images[0],
      images,
      currency,
      currentPrice: toAmount(priceAmount),
      originalPrice: toAmount(originalAmount),
      availability: availabilityFromSchema(og(doc, 'product:availability', 'og:availability')),
    },
  };
}

/** Used by the scorer: an explicit `og:type=product` is a strong page signal. */
export function hasProductOgType(doc: Document): boolean {
  const type = og(doc, 'og:type')?.toLowerCase() ?? '';
  return type.includes('product');
}
