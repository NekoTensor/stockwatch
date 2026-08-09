/** URL normalisation and the small amount of product knowledge a URL carries. */

/**
 * Query parameters that identify a *campaign*, not a *product*. Leaving these
 * in means the same jacket tracked from an email link and from search looks
 * like two different products to the backend.
 */
const TRACKING_PARAMS = [
  /^utm_/i,
  /^ic_/i,
  /^gclid$/i,
  /^gclsrc$/i,
  /^dclid$/i,
  /^fbclid$/i,
  /^msclkid$/i,
  /^igshid$/i,
  /^ttclid$/i,
  /^srsltid$/i,
  /^_branch_match_id$/i,
  /^_bta_/i,
  /^mc_[ce]id$/i,
  /^ref$/i,
  /^ref_$/i,
  /^referrer$/i,
  /^source$/i,
  /^sourceid$/i,
  /^cm_(sp|re|mmc)$/i,
  /^pd_rd_/i,
  /^pf_rd_/i,
  /^psc$/i,
  /^th$/i,
  /^qid$/i,
  /^sr$/i,
  /^spm$/i,
  /^tracker$/i,
  /^camp$/i,
  /^creative(ASIN)?$/i,
  /^linkCode$/i,
  /^tag$/i,
  /^ascsubtag$/i,
];

export function parseUrl(url: string): URL | undefined {
  try {
    return new URL(url);
  } catch {
    return undefined;
  }
}

/** Lower-cased hostname with a leading "www." removed. */
export function normaliseHostname(url: string): string {
  const parsed = parseUrl(url);
  if (!parsed) return '';
  return parsed.hostname.toLowerCase().replace(/^www\d*\./, '');
}

/**
 * Strip campaign noise while preserving everything that selects the product.
 * Amazon's `/ref=…` path segment is a special case: it is navigation history
 * baked into the path, and it changes on every visit.
 */
export function cleanUrl(url: string): string {
  const parsed = parseUrl(url);
  if (!parsed) return url;

  for (const key of [...parsed.searchParams.keys()]) {
    if (TRACKING_PARAMS.some((pattern) => pattern.test(key))) {
      parsed.searchParams.delete(key);
    }
  }

  parsed.hash = '';
  parsed.pathname = parsed.pathname.replace(/\/ref=[^/]+/gi, '');

  return parsed.toString().replace(/\?$/, '');
}

/** Resolve a possibly-relative asset URL against the page it came from. */
export function absoluteUrl(value: string | undefined, base: string): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (trimmed.startsWith('data:')) return undefined; // placeholder pixels
  if (trimmed.startsWith('//')) return `https:${trimmed}`;
  try {
    return new URL(trimmed, base).toString();
  } catch {
    return undefined;
  }
}

/**
 * Product identifiers that live in the address bar. Ordered most-specific
 * first; the generic trailing-number rule is deliberately last.
 */
const ID_PATTERNS: Array<[RegExp, string]> = [
  [/\/dp\/([A-Z0-9]{10})(?:[/?]|$)/i, 'asin'], // Amazon
  [/\/gp\/product\/([A-Z0-9]{10})(?:[/?]|$)/i, 'asin'],
  [/\/itm\/(\d+)/i, 'itm'], // eBay
  [/-p(\d{6,})\.html/i, 'zara'], // Zara: …-p07840321.html
  [/\/productpage\.(\d{6,})\.html/i, 'hm'], // H&M: productpage.0713986001.html
  [/\/p\/([A-Za-z0-9_-]{4,})(?:[/?]|$)/i, 'path'],
  [/\/product\/([A-Za-z0-9_-]{4,})(?:[/?]|$)/i, 'path'],
  [/\/(\d{5,})\/buy(?:[/?]|$)/i, 'myntra'],
  [/[?&](?:pid|productId|product_id|skuId|itemId)=([^&]+)/i, 'query'],
  [/\/(\d{6,})(?:[/?]|$)/, 'numeric'],
];

export function productIdFromUrl(url: string): string | undefined {
  for (const [pattern] of ID_PATTERNS) {
    const match = url.match(pattern);
    if (match?.[1]) return decodeURIComponent(match[1]);
  }
  return undefined;
}

/**
 * A weak signal, not a verdict: almost every store puts *something* like
 * /p/, /dp/, /product/ or a long numeric id in a product URL. Used only to
 * nudge the confidence score, never to reject a page on its own.
 */
export function looksLikeProductUrl(url: string): boolean {
  const parsed = parseUrl(url);
  if (!parsed) return false;
  const path = parsed.pathname;

  const positives = [
    /\/dp\//i,
    /\/gp\/product\//i,
    /\/p\//i,
    /\/product[s]?\//i,
    /\/pd\//i,
    /\/itm\//i,
    /\/buy\b/i,
    /-p\d{4,}\.html/i,
    /productpage\.\d+\.html/i,
    /\/[^/]+-\d{5,}(?:\.html)?$/i,
  ];
  if (positives.some((pattern) => pattern.test(path))) return true;

  return /[?&](pid|productId|product_id|skuId|itemId)=/i.test(parsed.search);
}

/** Listing, search and cart pages that are definitely *not* a single product. */
export function looksLikeNonProductUrl(url: string): boolean {
  const parsed = parseUrl(url);
  if (!parsed) return false;
  const path = parsed.pathname.toLowerCase();

  if (path === '/' || path === '') return true;
  return [
    /\/cart\b/,
    /\/checkout\b/,
    /\/basket\b/,
    /\/bag\b/,
    /\/wishlist\b/,
    /\/orders?\b/,
    /\/account\b/,
    /\/login\b/,
    /\/signin\b/,
    /\/register\b/,
    /\/search\b/,
    /\/s\/?$/,
    /\/category\b/,
    /\/categories\b/,
    /\/collections?\/?$/,
    /\/help\b/,
    /\/customer-service\b/,
  ].some((pattern) => pattern.test(path));
}

/**
 * Pages the extension has no business touching: browser internals, the Web
 * Store (Chrome blocks script injection there), extension pages, local files.
 */
export function isRestrictedPage(url: string | undefined): boolean {
  if (!url) return true;
  return (
    /^(chrome|edge|brave|opera|vivaldi|about|devtools|view-source|moz-extension|chrome-extension|file):/i.test(
      url,
    ) ||
    /^https:\/\/chromewebstore\.google\.com/i.test(url) ||
    /^https:\/\/chrome\.google\.com\/webstore/i.test(url) ||
    /^https:\/\/microsoftedge\.microsoft\.com\/addons/i.test(url)
  );
}
