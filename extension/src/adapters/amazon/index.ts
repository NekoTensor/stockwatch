/**
 * Amazon — the one adapter that carries real selectors.
 *
 * Amazon publishes no JSON-LD Product and no `product:price:*` tags, so the
 * generic layers are left doing heuristics on a page that is mostly
 * navigation. These ids have been stable for years, and keeping them isolated
 * here means that when Amazon does change them, exactly one file needs editing.
 *
 * Note what is still *not* here: nothing overrides a value the generic layers
 * already found. Every hook fills a gap.
 */

import { parsePrice, toAmount } from '../../lib/price';
import { cleanText, normaliseKey } from '../../lib/text';
import type { DetectionContext, PriceData, ProductData, StockStatus, Variant } from '../../lib/types';
import { availabilityFromText } from '../../detection/util/availability';
import { queryAll, textOf } from '../../detection/util/dom';
import { matchesHost } from '../shared';
import type { AdapterInput, StoreAdapter } from '../types';

const DOMAINS = [
  'amazon.in', 'amazon.com', 'amazon.co.uk', 'amazon.de', 'amazon.fr', 'amazon.it',
  'amazon.es', 'amazon.ca', 'amazon.com.au', 'amazon.co.jp', 'amazon.ae', 'amazon.sg',
  'amazon.nl', 'amazon.se', 'amazon.pl', 'amazon.com.br', 'amazon.com.mx',
];

const TITLE = ['#productTitle', '#title span'];
const PRICE = [
  '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
  '#corePrice_feature_div .a-price .a-offscreen',
  '#priceblock_ourprice',
  '#priceblock_dealprice',
  '.a-price .a-offscreen',
];
const LIST_PRICE = [
  '#corePriceDisplay_desktop_feature_div .basisPrice .a-offscreen',
  '.basisPrice .a-offscreen',
  '#listPrice',
  '.priceBlockStrikePriceString',
];
const IMAGE = ['#landingImage', '#imgTagWrapperId img', '#main-image'];
const BRAND = ['#bylineInfo', '#brand'];
const AVAILABILITY = ['#availability span', '#availability', '#outOfStock'];
const VARIANTS = ['#variation_size_name li', '#variation_style_name li', '#variation_color_name li'];

const ASIN = /\/(?:dp|gp\/product)\/([A-Z0-9]{10})/i;

function firstText(doc: Document, selectors: string[]): string | undefined {
  for (const selector of selectors) {
    for (const el of queryAll(doc, selector)) {
      const text = cleanText(textOf(el));
      if (text) return text;
    }
  }
  return undefined;
}

export const AmazonAdapter: StoreAdapter = {
  id: 'amazon',
  label: 'Amazon',

  canHandle(ctx: DetectionContext): boolean {
    return matchesHost(ctx.hostname, DOMAINS);
  },

  detectProduct({ ctx, base }: AdapterInput): Partial<ProductData> | null {
    const contribution: Partial<ProductData> = {};

    if (!base.productName) {
      const title = firstText(ctx.doc, TITLE);
      if (title) contribution.productName = title;
    }

    if (!base.brand) {
      const raw = firstText(ctx.doc, BRAND);
      if (raw) {
        // "Visit the Levi's Store" / "Brand: Levi's"
        const brand = raw.replace(/^(visit the|brand:)\s*/i, '').replace(/\s*store$/i, '').trim();
        if (brand) contribution.brand = brand;
      }
    }

    if (!base.imageUrl) {
      for (const selector of IMAGE) {
        const el = ctx.doc.querySelector(selector);
        const url = el?.getAttribute('src') ?? el?.getAttribute('data-old-hires');
        if (url) {
          contribution.imageUrl = url;
          break;
        }
      }
    }

    if (!base.productId) {
      const match = ctx.url.match(ASIN);
      if (match?.[1]) {
        contribution.productId = match[1].toUpperCase();
        contribution.sku ??= match[1].toUpperCase();
      }
    }

    return Object.keys(contribution).length ? contribution : null;
  },

  detectPrice({ ctx, base }: AdapterInput): PriceData | null {
    if (base.currentPrice !== undefined) return null;

    const text = firstText(ctx.doc, PRICE);
    if (!text) return null;

    const parsed = parsePrice(text);
    if (!parsed) return null;

    const listText = firstText(ctx.doc, LIST_PRICE);
    const listPrice = listText ? toAmount(listText) : undefined;

    return {
      currentPrice: parsed.amount,
      currency: parsed.currency,
      originalPrice: listPrice && listPrice > parsed.amount ? listPrice : undefined,
    };
  },

  detectAvailability({ ctx }: AdapterInput): StockStatus | null {
    const text = firstText(ctx.doc, AVAILABILITY);
    if (!text) return null;
    const status = availabilityFromText(text);
    return status === 'unknown' ? null : status;
  },

  detectVariants({ ctx, base }: AdapterInput): Variant[] | null {
    if (base.variants?.length) return null;

    for (const selector of VARIANTS) {
      const variants: Variant[] = [];
      const seen = new Set<string>();

      for (const el of queryAll(ctx.doc, selector)) {
        const name = cleanText(textOf(el)) ?? cleanText(el.getAttribute('title'));
        if (!name || name.length > 40) continue;
        const key = normaliseKey(name);
        if (!key || seen.has(key)) continue;
        seen.add(key);

        const className = typeof el.className === 'string' ? el.className : '';
        variants.push({
          id: el.getAttribute('data-defaultasin') ?? el.getAttribute('data-asin') ?? name,
          name,
          type: selector.includes('size') ? 'size' : 'generic',
          availability: /swatchUnavailable|unavailable/i.test(className) ? 'out_of_stock' : 'in_stock',
          source: 'adapter',
        });
      }

      if (variants.length >= 2) return variants;
    }

    return null;
  },

  isProductPage(ctx: DetectionContext): boolean | undefined {
    return ASIN.test(ctx.url) ? true : undefined;
  },
};
