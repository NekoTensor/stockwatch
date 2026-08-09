/**
 * Layer 6 — visual/structural heuristics over the rendered page.
 *
 * The layer of last resort, and the one that decides whether an unknown store
 * works at all. Nothing in here is store-specific: it looks for the things a
 * *shopper* looks for — the biggest heading, the boldest price, a row of small
 * buttons some of which are greyed out, an "Add to bag" control.
 */

import { CURRENCY_MARKER, PRICE_PATTERN, currencyFromHostname, currencyFromText, parseAmount } from '../../lib/price';
import { cleanText, normaliseKey } from '../../lib/text';
import type { Candidate, DetectionContext, StockStatus, Variant, VariantType } from '../../lib/types';
import { availabilityFromText } from '../util/availability';
import {
  VARIANT_CONTAINER_HINT,
  VARIANT_TOKEN,
  accessibleLabel,
  domDistance,
  groupLabelFor,
  isDisabledLike,
  isHiddenDeep,
  isStruckThrough,
  queryAll,
  textOf,
} from '../util/dom';

/**
 * Regions that hold *other* products: recommendations, carts, navigation.
 *
 * The token boundaries are load-bearing. A bare `nav` alternative matches
 * inside "unavailable", which silently discarded every sold-out swatch on
 * Amazon as though it were navigation. Boundaries are written as "not a letter
 * or digit" rather than `\b`, because `_` is a word character and class names
 * like `mini_bag` would otherwise slip through.
 */
const NOISE_TOKENS = [
  'recommend', 'related', 'similar', 'also-?like', 'you-?may', 'carousel',
  'cross-?sell', 'up-?sell', 'footer', 'header', 'nav', 'menu', 'cart',
  'basket', 'mini-?bag', 'wishlist', 'recently-?viewed', 'sponsor', 'advert', 'banner',
];
const NOISE_CONTAINER = new RegExp(`(?:^|[^a-z0-9])(?:${NOISE_TOKENS.join('|')})(?:[^a-z0-9]|$)`, 'i');

const MAX_ELEMENTS_SCANNED = 8000;

function inNoiseRegion(el: Element): boolean {
  let node: Element | null = el;
  let hops = 0;
  while (node && hops < 14) {
    if (['NAV', 'FOOTER', 'HEADER', 'ASIDE', 'SCRIPT', 'STYLE', 'NOSCRIPT'].includes(node.tagName)) return true;
    const attrs = `${node.id} ${typeof node.className === 'string' ? node.className : ''} ${
      node.getAttribute('data-testid') ?? ''
    }`;
    if (NOISE_CONTAINER.test(attrs)) return true;
    node = node.parentElement;
    hops += 1;
  }
  return false;
}

const SCOPE_SELECTORS = [
  '[class*="product-detail" i]',
  '[class*="productDetail" i]',
  '[id*="product-detail" i]',
  '[class*="pdp" i]',
  '[id*="pdp" i]',
  '[data-testid*="product" i]',
  '[itemtype*="Product" i]',
  'main',
  'article',
];

/**
 * The subtree most likely to be the product detail area.
 *
 * A scope is only accepted if it **contains the product's own heading**. Taking
 * the first selector match without that check is how H&M ended up scoped to a
 * `<section id="…pdp…">` holding neither the title, the price nor the size
 * grid — every downstream heuristic then found nothing, on a page that has all
 * three.
 *
 * Where several candidates qualify the largest wins, not the smallest: the job
 * of scoping is only to skip obviously unrelated markup, and excluding *other*
 * products is `inNoiseRegion`'s job, done per element.
 */
function productScope(doc: Document, titleEl: Element | undefined): ParentNode {
  const candidates = SCOPE_SELECTORS.flatMap((selector) => queryAll(doc, selector)).filter(
    (el) => !isHiddenDeep(el) && textOf(el).length > 40,
  );

  if (titleEl) {
    const containing = candidates.filter((el) => el !== titleEl && el.contains(titleEl));
    if (containing.length) {
      return containing.reduce((best, el) => (textOf(el).length > textOf(best).length ? el : best));
    }
  }

  return doc.querySelector('main') ?? doc.querySelector('article') ?? doc.body ?? doc;
}

// ---------------------------------------------------------------- title ----

const TITLE_SELECTORS = [
  'h1[itemprop="name"]',
  '[itemprop="name"]',
  'h1[class*="product" i]',
  'h1[data-testid*="name" i]',
  'h1[data-testid*="title" i]',
  '[class*="product-name" i]',
  '[class*="productName" i]',
  '[class*="product-title" i]',
  '[class*="pdp-title" i]',
  '[class*="pdp-name" i]',
  'h1',
];

function findTitleElement(doc: Document): Element | undefined {
  for (const selector of TITLE_SELECTORS) {
    for (const el of queryAll(doc, selector)) {
      if (isHiddenDeep(el) || inNoiseRegion(el)) continue;
      const text = textOf(el);
      if (text.length >= 3 && text.length <= 200) return el;
    }
  }
  return undefined;
}

// ---------------------------------------------------------------- price ----

interface PriceCandidate {
  el: Element;
  amount: number;
  currency?: string;
  struck: boolean;
  score: number;
}

const PRICE_ATTR_HINT = /(price|amount|cost|mrp|value|final|selling|offer|deal|sale)/i;

function fontSizeOf(el: Element): number {
  const view = el.ownerDocument?.defaultView;
  if (!view?.getComputedStyle) return 0;
  try {
    return Number.parseFloat(view.getComputedStyle(el).fontSize) || 0;
  } catch {
    return 0;
  }
}

function collectPriceCandidates(scope: ParentNode, titleEl: Element | undefined): PriceCandidate[] {
  const elements = queryAll(scope, '*').slice(0, MAX_ELEMENTS_SCANNED);
  const raw: PriceCandidate[] = [];

  for (const el of elements) {
    const text = textOf(el);
    // A tight wrapper around a price is short. Long text means we are looking
    // at a paragraph that merely mentions money.
    if (!text || text.length > 40) continue;
    if (!CURRENCY_MARKER.test(text) && !/^\s*[\d.,\s]+\s*$/.test(text)) continue;
    if (!PRICE_PATTERN.test(text)) continue;
    if (isHiddenDeep(el) || inNoiseRegion(el)) continue;

    const amount = parseAmount(text);
    if (amount === undefined || amount <= 0 || amount > 100_000_000) continue;

    // Bare numbers without any currency marker are too weak on their own.
    const currency = currencyFromText(text);
    if (!currency && !CURRENCY_MARKER.test(text)) continue;

    raw.push({ el, amount, currency, struck: isStruckThrough(el), score: 0 });
  }

  // Keep only the innermost match: "₹12,990" beats its wrapper "MRP ₹12,990".
  const innermost = raw.filter(
    (candidate) => !raw.some((other) => other !== candidate && candidate.el.contains(other.el)),
  );

  for (const candidate of innermost) {
    let score = 0;

    const attrs = `${candidate.el.id} ${
      typeof candidate.el.className === 'string' ? candidate.el.className : ''
    } ${candidate.el.getAttribute('data-testid') ?? ''} ${candidate.el.parentElement?.className ?? ''}`;
    if (PRICE_ATTR_HINT.test(attrs)) score += 4;

    if (titleEl) {
      const distance = domDistance(candidate.el, titleEl);
      if (distance <= 6) score += 4;
      else if (distance <= 12) score += 2;
      else if (distance > 20) score -= 2;
    }

    const size = fontSizeOf(candidate.el);
    if (size >= 24) score += 3;
    else if (size >= 18) score += 2;

    if (candidate.struck) score -= 5; // struck prices are the *old* price
    if (/^\s*[^\d]*[\d.,\s]+\s*$/.test(textOf(candidate.el))) score += 2; // just a price, no prose

    candidate.score = score;
  }

  return innermost.sort((a, b) => b.score - a.score);
}

interface PriceReading {
  currentPrice?: number;
  originalPrice?: number;
  currency?: string;
}

function readPrices(candidates: PriceCandidate[], hostname: string): PriceReading {
  const live = candidates.filter((c) => !c.struck);
  const struck = candidates.filter((c) => c.struck);

  const current = live[0] ?? candidates[0];
  if (!current) return {};

  // The original price is the struck-through one, or — failing that — a
  // clearly larger sibling price sitting right next to the current one.
  let original = struck.find((c) => c.amount > current.amount);
  if (!original) {
    original = live
      .slice(1)
      .find((c) => c.amount > current.amount && c.amount < current.amount * 20 && domDistance(c.el, current.el) <= 8);
  }

  return {
    currentPrice: current.amount,
    originalPrice: original && original.amount > current.amount ? original.amount : undefined,
    currency:
      current.currency ??
      candidates.find((c) => c.currency)?.currency ??
      currencyFromHostname(hostname),
  };
}

// --------------------------------------------------------------- images ----

const BAD_IMAGE = /(logo|sprite|icon|placeholder|loader|spinner|blank|pixel|1x1|avatar|badge|flag|payment|banner)/i;

function firstFromSrcset(value: string | null): string | undefined {
  if (!value) return undefined;
  const first = value.split(',')[0]?.trim().split(/\s+/)[0];
  return first || undefined;
}

function collectImages(scope: ParentNode, titleEl: Element | undefined, productName?: string): string[] {
  const nameWords = (productName ?? '')
    .toLowerCase()
    .split(/\s+/)
    .filter((word) => word.length > 3);

  const scored: Array<{ url: string; score: number }> = [];

  for (const el of queryAll(scope, 'img, picture source').slice(0, 400)) {
    const url =
      el.getAttribute('src') ??
      firstFromSrcset(el.getAttribute('srcset')) ??
      el.getAttribute('data-src') ??
      firstFromSrcset(el.getAttribute('data-srcset')) ??
      el.getAttribute('data-original') ??
      el.getAttribute('data-lazy-src');
    if (!url || url.startsWith('data:')) continue;
    if (BAD_IMAGE.test(url)) continue;
    if (inNoiseRegion(el)) continue;

    let score = 0;
    const alt = (el.getAttribute('alt') ?? '').toLowerCase();
    if (BAD_IMAGE.test(alt)) continue;

    const attrs = `${typeof el.className === 'string' ? el.className : ''} ${el.getAttribute('data-testid') ?? ''}`;
    if (/(product|gallery|zoom|main|hero|primary|media)/i.test(attrs)) score += 3;
    if (nameWords.length && nameWords.some((word) => alt.includes(word))) score += 3;
    if (titleEl && domDistance(el, titleEl) <= 12) score += 2;

    const width = Number.parseInt(el.getAttribute('width') ?? '', 10);
    if (Number.isFinite(width) && width >= 300) score += 2;
    if ((el as HTMLImageElement).naturalWidth >= 400) score += 2;

    scored.push({ url, score });
  }

  const seen = new Set<string>();
  return scored
    .sort((a, b) => b.score - a.score)
    .map((entry) => entry.url)
    .filter((url) => (seen.has(url) ? false : (seen.add(url), true)))
    .slice(0, 8);
}

// ------------------------------------------------------------- variants ----

function typeFromLabel(label: string, sample: string): VariantType {
  const hint = `${label} ${sample}`.toLowerCase();
  if (/shade/.test(hint)) return 'shade';
  if (/colou?r/.test(hint)) return 'color';
  if (/\b\d+\s?(gb|tb|mb)\b/.test(hint) || /capacity|storage|memory/.test(hint)) return 'capacity';
  if (/length/.test(hint)) return 'length';
  if (/flavou?r|scent/.test(hint)) return 'flavor';
  if (/\bsize\b|\bfit\b/.test(hint)) return 'size';
  if (VARIANT_TOKEN.test(sample)) return 'size';
  return 'generic';
}

const STATE_OUT = /out[-_\s]?of[-_\s]?stock|sold[-_\s]?out|unavailable|notify/i;
const STATE_IN = /\bin[-_\s]?stock\b|\bavailable\b/i;

/**
 * Availability of a single variant control.
 *
 * State is frequently carried by an attribute rather than by looks, and often
 * on a *child* of the control: H&M writes `aria-label="Size XL: Sold out."` and
 * `data-testid="014-out-of-stock"` on the cell inside the button.
 */
function variantAvailability(el: Element): StockStatus {
  if (isDisabledLike(el)) return 'out_of_stock';

  const descriptors = [
    el.getAttribute('aria-label') ?? '',
    el.getAttribute('title') ?? '',
    el.getAttribute('data-testid') ?? '',
    ...queryAll(el, '[aria-label], [title], [data-testid]')
      .slice(0, 8)
      .flatMap((child) => [
        child.getAttribute('aria-label') ?? '',
        child.getAttribute('title') ?? '',
        child.getAttribute('data-testid') ?? '',
      ]),
  ].join(' ');

  if (STATE_OUT.test(descriptors)) return 'out_of_stock';
  if (availabilityFromText(textOf(el)) === 'out_of_stock') return 'out_of_stock';
  if (STATE_IN.test(descriptors)) return 'in_stock';

  // A control that is present and not switched off is buyable. That is a
  // positive statement about *this* control, not about the whole product.
  return 'in_stock';
}

/**
 * Variant widgets are rows of small controls that share a parent. Group every
 * plausible control by its parent, then keep the groups that look like a
 * size/shade picker rather than a menu.
 */
/**
 * Walk out of wrappers that contribute nothing but styling.
 *
 * `<div class="hashed"><div>M</div></div>` — the inner div holds the text, the
 * outer one holds the class that says whether M is available and sits beside
 * its fellow sizes. The outer one is the control.
 */
function unwrapControl(el: Element, label: string): Element {
  let node = el;
  for (let hops = 0; hops < 3; hops += 1) {
    const parent = node.parentElement;
    if (!parent || parent.children.length !== 1) break;
    if (cleanText(textOf(parent)) !== label) break;
    node = parent;
  }
  return node;
}

function collectVariants(scope: ParentNode): Variant[] {
  const controls = queryAll(
    scope,
    'button, [role="radio"], [role="option"], [role="button"], label, li, a, div, span, option',
  ).slice(0, 6000);

  const groups = new Map<Element, Element[]>();
  const claimed = new Set<Element>();

  for (const el of controls) {
    if (isHiddenDeep(el) && el.tagName !== 'OPTION') continue;
    if (inNoiseRegion(el)) continue;

    const label = cleanText(accessibleLabel(el));
    if (!label || label.length > 24) continue;

    // Plain containers are only considered when they are a leaf whose entire
    // text *is* a variant token. Modern storefronts build size pickers out of
    // bare <div>s with hashed class names and no data attributes, so requiring
    // `data-value` missed them entirely — but accepting any short-texted div
    // would sweep up half the page.
    const isPlainContainer = ['DIV', 'SPAN', 'A'].includes(el.tagName);
    if (isPlainContainer && !el.hasAttribute('data-value')) {
      if (el.children.length > 0 || !VARIANT_TOKEN.test(label)) continue;
    }

    // Those same pickers wrap each option in a styling div, so the options are
    // cousins rather than siblings and grouping by parent yields groups of one.
    // Climb through wrappers that add no text of their own; the outermost is
    // also where the disabled/selected class usually lives.
    const control = isPlainContainer ? unwrapControl(el, label) : el;
    if (claimed.has(control)) continue;
    claimed.add(control);

    const parent = control.parentElement;
    if (!parent) continue;

    const list = groups.get(parent) ?? [];
    list.push(control);
    groups.set(parent, list);
  }

  let best: { variants: Variant[]; score: number } | undefined;

  for (const [parent, members] of groups) {
    if (members.length < 2 || members.length > 60) continue;

    const labels = members.map((el) => cleanText(accessibleLabel(el)) ?? '');
    const tokenHits = labels.filter((label) => VARIANT_TOKEN.test(label)).length;

    const containerAttrs = [
      parent.id,
      typeof parent.className === 'string' ? parent.className : '',
      parent.getAttribute('data-testid') ?? '',
      parent.getAttribute('aria-label') ?? '',
      groupLabelFor(members[0]),
    ].join(' ');
    const containerHit = VARIANT_CONTAINER_HINT.test(containerAttrs);

    // Either the labels look like sizes, or the container says it is a picker
    // and the labels are short enough to be options rather than sentences.
    const tokenRatio = tokenHits / members.length;
    const shortLabels = labels.every((label) => label.length <= 16);
    if (!(tokenRatio >= 0.5 || (containerHit && shortLabels && tokenHits >= 1))) continue;

    const groupLabel = groupLabelFor(members[0]);
    const seen = new Set<string>();
    const variants: Variant[] = [];

    for (const el of members) {
      const name = cleanText(accessibleLabel(el));
      if (!name) continue;
      const key = normaliseKey(name);
      if (!key || seen.has(key)) continue;
      seen.add(key);

      variants.push({
        id: el.getAttribute('data-value') ?? el.getAttribute('value') ?? el.getAttribute('id') ?? name,
        name,
        type: typeFromLabel(`${containerAttrs} ${groupLabel}`, name),
        availability: variantAvailability(el),
        group: cleanText(groupLabel) || undefined,
        source: 'dom',
      });
    }

    if (variants.length < 2) continue;

    const score = variants.length + tokenHits * 2 + (containerHit ? 4 : 0);
    if (!best || score > best.score) best = { variants, score };
  }

  return best?.variants ?? [];
}

// --------------------------------------------------------- availability ----

const BUY_BUTTON = /\b(add to (cart|bag|basket)|add to my bag|buy now|buy it now|order now|add item|shop now)\b/i;
const NOTIFY_BUTTON = /\b(notify me|email me|remind me|coming soon|join the waitlist|back in stock)\b/i;

export function detectPageAvailability(scope: ParentNode): { status: StockStatus; hasBuyButton: boolean } {
  const buttons = queryAll(scope, 'button, a[role="button"], input[type="submit"], [class*="btn" i], [class*="button" i]').slice(
    0,
    600,
  );

  let hasBuyButton = false;
  let buyEnabled = false;
  let notify = false;

  for (const el of buttons) {
    const label = `${textOf(el)} ${el.getAttribute('aria-label') ?? ''} ${el.getAttribute('value') ?? ''}`;
    if (BUY_BUTTON.test(label)) {
      hasBuyButton = true;
      if (!isDisabledLike(el)) buyEnabled = true;
    }
    if (NOTIFY_BUTTON.test(label)) notify = true;
  }

  if (buyEnabled) return { status: 'in_stock', hasBuyButton };
  if (hasBuyButton) return { status: 'out_of_stock', hasBuyButton };
  if (notify) return { status: 'out_of_stock', hasBuyButton };
  return { status: 'unknown', hasBuyButton };
}

// -------------------------------------------------------------- listing ----

/**
 * Is this a grid of products rather than one product?
 *
 * A category page has every individual signal a product page has — a heading, a
 * price, an "Add to bag" button, a breadcrumb — so no single check separates
 * them. What is structurally different is *repetition*: three or more sibling
 * elements of the same kind, each carrying its own price and its own link.
 *
 * Recommendation rails are excluded via `inNoiseRegion`, and the siblings must
 * share a tag so that "header + main + footer, all of which mention money" does
 * not count.
 */
export function looksLikeListingGrid(doc: Document): boolean {
  const containers = queryAll(doc, 'ul, ol, section, div, main').slice(0, 2500);

  const isCard = (el: Element): boolean => {
    const text = textOf(el);
    if (!text || text.length > 400) return false;
    if (!CURRENCY_MARKER.test(text) || !PRICE_PATTERN.test(text)) return false;
    return Boolean(el.querySelector('a, h2, h3, h4, img'));
  };

  for (const container of containers) {
    const children = Array.from(container.children);
    if (children.length < 3) continue;
    if (inNoiseRegion(container)) continue;

    const byTag = new Map<string, Element[]>();
    for (const child of children) {
      byTag.set(child.tagName, [...(byTag.get(child.tagName) ?? []), child]);
    }

    for (const siblings of byTag.values()) {
      if (siblings.length < 3) continue;
      if (siblings.filter(isCard).length >= 3) return true;
    }
  }

  return false;
}

// -------------------------------------------------------- brand/category ----

function detectBrand(scope: ParentNode, titleEl: Element | undefined): string | undefined {
  const selectors = ['[itemprop="brand"]', '[class*="brand" i]', '[data-testid*="brand" i]', 'a[href*="/brand" i]'];
  for (const selector of selectors) {
    for (const el of queryAll(scope, selector)) {
      if (isHiddenDeep(el) || inNoiseRegion(el)) continue;
      if (titleEl && domDistance(el, titleEl) > 14) continue;
      const text = cleanText(textOf(el));
      if (text && text.length >= 2 && text.length <= 40) return text;
    }
  }
  return undefined;
}

function detectCategory(doc: Document): string | undefined {
  const crumbs = queryAll(
    doc,
    'nav[aria-label*="breadcrumb" i] li, [class*="breadcrumb" i] li, [class*="breadcrumb" i] a, ol[itemtype*="BreadcrumbList" i] li',
  )
    .map((el) => cleanText(textOf(el)))
    .filter((text): text is string => typeof text === 'string' && text.length <= 60);

  if (crumbs.length < 2) return undefined;
  // The last crumb is usually the product itself; the one before it is the category.
  return crumbs[crumbs.length - 2];
}

// ------------------------------------------------------------------ main ----

export interface DomSignals {
  hasTitle: boolean;
  hasPrice: boolean;
  hasBuyButton: boolean;
  hasVariants: boolean;
  hasBreadcrumb: boolean;
  hasGallery: boolean;
  listingGrid: boolean;
}

export function extractDom(ctx: DetectionContext): { candidate: Candidate; signals: DomSignals } {
  // The title is found across the whole document, then used to validate the
  // scope — a product area that does not contain the product's name is not the
  // product area.
  const titleEl = findTitleElement(ctx.doc);
  const scope = productScope(ctx.doc, titleEl);
  const productName = titleEl ? cleanText(textOf(titleEl)) : undefined;

  const priceCandidates = collectPriceCandidates(scope, titleEl);
  const prices = readPrices(priceCandidates, ctx.hostname);

  const variants = collectVariants(scope);
  const { status, hasBuyButton } = detectPageAvailability(scope);
  const images = collectImages(scope, titleEl, productName);

  const signals: DomSignals = {
    hasTitle: Boolean(productName),
    hasPrice: prices.currentPrice !== undefined,
    hasBuyButton,
    hasVariants: variants.length > 0,
    hasBreadcrumb: queryAll(ctx.doc, '[class*="breadcrumb" i], nav[aria-label*="breadcrumb" i]').length > 0,
    hasGallery: images.length > 1,
    listingGrid: looksLikeListingGrid(ctx.doc),
  };

  return {
    candidate: {
      source: 'dom',
      confidence: 0.5,
      data: {
        productName,
        brand: detectBrand(scope, titleEl),
        category: detectCategory(ctx.doc),
        imageUrl: images[0],
        images,
        currency: prices.currency,
        currentPrice: prices.currentPrice,
        originalPrice: prices.originalPrice,
        availability: status,
        variants,
      },
    },
    signals,
  };
}
