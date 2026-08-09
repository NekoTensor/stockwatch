/** Small text helpers shared by every extraction layer. */

/** In JavaScript `\s` already covers NBSP, thin/narrow spaces and the BOM. */
const WHITESPACE = /\s+/g;

const ZWSP = 0x200b; // zero-width space
const ZWJ = 0x200d; // zero-width joiner (ZWNJ sits between the two)

/**
 * Zero-width characters are invisible but are *not* matched by `\s`, so they
 * survive naive trimming and then break exact-match comparisons later.
 */
function stripInvisible(input: string): string {
  if (!input) return input;
  let out = '';
  for (const ch of input) {
    const cp = ch.codePointAt(0) ?? 0;
    if (cp >= ZWSP && cp <= ZWJ) continue;
    out += ch;
  }
  return out;
}

/** Collapse whitespace, trim, and drop the zero-width junk that CMSes love. */
export function clean(input: unknown): string | undefined {
  if (typeof input !== 'string') return undefined;
  const out = stripInvisible(input).replace(WHITESPACE, ' ').trim();
  return out.length ? out : undefined;
}

/** Decode the handful of HTML entities that survive inside meta tag content. */
export function decodeEntities(input: string): string {
  if (!input.includes('&')) return input;
  const named: Record<string, string> = {
    amp: '&',
    lt: '<',
    gt: '>',
    quot: '"',
    apos: "'",
    nbsp: String.fromCharCode(160),
    rsquo: String.fromCharCode(8217),
    lsquo: String.fromCharCode(8216),
    ldquo: String.fromCharCode(8220),
    rdquo: String.fromCharCode(8221),
    hellip: String.fromCharCode(8230),
    ndash: String.fromCharCode(8211),
    mdash: String.fromCharCode(8212),
  };
  return input.replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (match, entity: string) => {
    const key = entity.toLowerCase();
    try {
      if (key.startsWith('#x')) return String.fromCodePoint(parseInt(key.slice(2), 16));
      if (key.startsWith('#')) return String.fromCodePoint(parseInt(key.slice(1), 10));
    } catch {
      return match; // Out-of-range code point: leave the entity exactly as written.
    }
    return named[key] ?? match;
  });
}

export function cleanText(input: unknown): string | undefined {
  const raw = clean(input);
  return raw ? clean(decodeEntities(raw)) : undefined;
}

/**
 * Product names arrive with the shop's name bolted on: "Leather Jacket | ZARA",
 * "Buy Nike Air Max 90 Online - Myntra". Strip the SEO boilerplate so the popup
 * shows the product rather than the page title.
 */
export function stripSiteSuffix(title: string, storeNames: string[] = []): string {
  let out = title;

  const separators = ['|', String.fromCharCode(8211), String.fromCharCode(8212), ' - ', '::'];
  for (const sep of separators) {
    const parts = out.split(sep);
    if (parts.length < 2) continue;
    const kept = parts.filter((part) => {
      const p = part.trim();
      if (!p) return false;
      // Compare on the normalised key so "Studio Beauty" matches the
      // "studiobeauty" derived from the hostname.
      if (storeNames.some((s) => s && normaliseKey(p) === normaliseKey(s))) return false;
      return !/^(shop online|online shopping|buy online|official (site|store|online store)|free shipping|official)$/i.test(
        p,
      );
    });
    if (kept.length && kept.length < parts.length) out = kept.join(sep);
  }

  out = out
    .replace(/^\s*(buy|shop|order)\s+/i, '')
    .replace(/\s+(online|online at best prices?|at best prices? in india)\s*$/i, '')
    .trim();

  return out || title.trim();
}

export function truncate(input: string, max: number): string {
  return input.length <= max ? input : `${input.slice(0, max - 1).trimEnd()}${String.fromCharCode(8230)}`;
}

/** Title-case a hostname fragment: "nykaafashion" -> "Nykaafashion". */
export function titleCase(input: string): string {
  return input
    .split(/[\s\-_]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * Case/whitespace/punctuation-insensitive key. Variants extracted by different
 * layers ("UK 8" from JSON-LD, "uk-8" from a button) have to collapse onto the
 * same key or the merge step will show every size twice.
 */
export function normaliseKey(input: string): string {
  return input
    .toLowerCase()
    .replace(/[\s._\-/\\]+/g, '')
    .replace(/[^\p{L}\p{N}]/gu, '');
}
