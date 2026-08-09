/**
 * Layer 2 — schema.org expressed as microdata attributes.
 *
 * Older storefronts (and most Magento/WooCommerce themes) never emit JSON-LD
 * but do annotate their markup with `itemscope`/`itemprop`. It carries the same
 * vocabulary as JSON-LD, so it is nearly as trustworthy — it is just spread
 * across the DOM instead of sitting in one script tag.
 */

import { parsePrice, toAmount } from '../../lib/price';
import { cleanText } from '../../lib/text';
import type { Candidate, DetectionContext } from '../../lib/types';
import { availabilityFromSchema } from '../util/availability';
import { queryAll, textOf } from '../util/dom';

/** The value of an itemprop depends on the element carrying it. */
function propValue(el: Element): string | undefined {
  const tag = el.tagName;
  if (tag === 'META') return cleanText(el.getAttribute('content'));
  if (tag === 'IMG' || tag === 'SOURCE' || tag === 'IFRAME')
    return cleanText(el.getAttribute('src') ?? el.getAttribute('content'));
  if (tag === 'A' || tag === 'LINK' || tag === 'AREA') return cleanText(el.getAttribute('href'));
  if (tag === 'TIME') return cleanText(el.getAttribute('datetime') ?? textOf(el));
  if (tag === 'DATA') return cleanText(el.getAttribute('value') ?? textOf(el));
  return cleanText(el.getAttribute('content') ?? textOf(el));
}

/**
 * Collect itemprops belonging to `scope`, stopping at nested itemscopes so an
 * embedded Review's `name` is not mistaken for the product's name. Nested
 * scopes we *do* care about (offers, brand) are followed explicitly.
 */
function propsIn(scope: Element, follow: Set<string>): Map<string, string[]> {
  const result = new Map<string, string[]>();

  const visit = (el: Element) => {
    for (const child of Array.from(el.children)) {
      const prop = child.getAttribute('itemprop');
      const isScope = child.hasAttribute('itemscope');

      if (prop && !isScope) {
        const value = propValue(child);
        if (value) {
          const list = result.get(prop) ?? [];
          list.push(value);
          result.set(prop, list);
        }
      }

      if (isScope) {
        // Only descend into nested entities we asked for (offers, brand).
        if (prop && follow.has(prop)) visit(child);
        continue;
      }

      visit(child);
    }
  };

  visit(scope);
  return result;
}

function first(map: Map<string, string[]>, key: string): string | undefined {
  return map.get(key)?.[0];
}

export function extractMicrodata(ctx: DetectionContext): Candidate | undefined {
  const scopes = queryAll(ctx.doc, '[itemscope][itemtype*="schema.org/Product" i], [itemscope][itemtype*="/Product" i]');
  if (!scopes.length) return undefined;

  // Deepest scope wins: an outer scope may wrap a whole listing page.
  const scope = scopes.sort((a, b) => b.querySelectorAll('[itemprop]').length - a.querySelectorAll('[itemprop]').length)[0];
  const props = propsIn(scope, new Set(['offers', 'brand', 'aggregateRating', 'priceSpecification']));

  const priceText = first(props, 'price') ?? first(props, 'lowPrice');
  const currentPrice = toAmount(priceText) ?? parsePrice(priceText)?.amount;
  const currency = first(props, 'priceCurrency')?.toUpperCase() ?? parsePrice(priceText)?.currency;

  const images = (props.get('image') ?? []).slice(0, 8);
  const name = first(props, 'name');

  if (!name && currentPrice === undefined) return undefined;

  return {
    source: 'microdata',
    confidence: 0.8,
    data: {
      productName: name,
      brand: first(props, 'brand'),
      description: first(props, 'description'),
      sku: first(props, 'sku') ?? first(props, 'mpn'),
      productId: first(props, 'productID') ?? first(props, 'sku'),
      category: first(props, 'category'),
      canonicalUrl: first(props, 'url'),
      imageUrl: images[0],
      images,
      currency,
      currentPrice,
      originalPrice: toAmount(first(props, 'highPrice')),
      availability: availabilityFromSchema(first(props, 'availability')),
    },
  };
}
