/**
 * Money parsing.
 *
 * Prices on the web are a mess: "Rs. 2,499/-", "1.299,99 EUR", "$1,299.99",
 * "MRP 3,999 (incl. of all taxes)". This module turns any of those into
 * `{ amount, currency }` without guessing wildly - where a string is genuinely
 * ambiguous we prefer the reading that does not invent money.
 */

export interface ParsedPrice {
  amount: number;
  currency?: string;
}

/**
 * Symbol/code patterns, longest-first so "A$" wins over "$" and the bare
 * dollar sign is only reached once every stronger claim has failed.
 */
const CURRENCY_TOKENS: Array<[RegExp, string]> = [
  [/\bA\$|\bAU\$/i, 'AUD'],
  [/\bCA?\$/i, 'CAD'],
  [/\bNZ\$/i, 'NZD'],
  [/\bS\$|\bSGD\b/i, 'SGD'],
  [/\bHK\$/i, 'HKD'],
  [/\bR\$/i, 'BRL'],
  [/\bMX\$|\bMXN\b/i, 'MXN'],
  [/[₹]|\bRs\.?\b|\bINR\b|\bRupees?\b/i, 'INR'],
  [/[€]|\bEUR\b/i, 'EUR'],
  [/[£]|\bGBP\b/i, 'GBP'],
  [/\bCN[¥]|\bRMB\b|\bCNY\b/i, 'CNY'],
  [/[¥]|\bJPY\b/i, 'JPY'],
  [/[₩]|\bKRW\b/i, 'KRW'],
  [/[₽]|\bRUB\b/i, 'RUB'],
  [/\bAED\b|د\.إ/i, 'AED'],
  [/\bSAR\b|﷼/i, 'SAR'],
  [/[₺]|\bTRY\b/i, 'TRY'],
  [/[฿]|\bTHB\b/i, 'THB'],
  [/[₫]|\bVND\b/i, 'VND'],
  [/[₴]|\bUAH\b/i, 'UAH'],
  [/\bzł\b|\bPLN\b/i, 'PLN'],
  [/\bCHF\b/i, 'CHF'],
  [/\bSEK\b/i, 'SEK'],
  [/\bNOK\b/i, 'NOK'],
  [/\bDKK\b/i, 'DKK'],
  [/\bRM\b|\bMYR\b/i, 'MYR'],
  [/\bRp\b|\bIDR\b/i, 'IDR'],
  [/[₱]|\bPHP\b/i, 'PHP'],
  [/[₦]|\bNGN\b/i, 'NGN'],
  [/\bZAR\b/i, 'ZAR'],
  [/\bUSD\b|\$/, 'USD'],
];

const SYMBOLS: Record<string, string> = {
  INR: '₹',
  USD: '$',
  EUR: '€',
  GBP: '£',
  JPY: '¥',
  CNY: '¥',
  KRW: '₩',
  RUB: '₽',
  AUD: 'A$',
  CAD: 'C$',
  SGD: 'S$',
  HKD: 'HK$',
  NZD: 'NZ$',
  BRL: 'R$',
  TRY: '₺',
  THB: '฿',
  VND: '₫',
  PHP: '₱',
  NGN: '₦',
  ZAR: 'R',
  PLN: 'zł',
  IDR: 'Rp',
  MYR: 'RM',
};

/**
 * The longest run of digits and separators: 12,990.00 / 1.299,99 / 2 499 / 45.
 *
 * Deliberately permissive rather than a grammar of grouping rules — writing
 * those rules out means picking a locale, and "1,24,999" (Indian lakh grouping)
 * is not the same grammar as "1,299". We grab the whole run and let
 * `parseAmount` work out what the separators meant. Requiring a digit at both
 * ends stops it swallowing trailing punctuation.
 */
export const PRICE_PATTERN = /\d[\d.,\s']*\d|\d/;

/** Any currency marker at all - used to decide whether a DOM node is a price. */
export const CURRENCY_MARKER =
  /[₹$€£¥₩₽₺฿₫₴₱₦]|\b(?:INR|USD|EUR|GBP|JPY|CNY|AED|SAR|SGD|AUD|CAD|CHF|SEK|NOK|DKK|PLN|ZAR|MYR|IDR|PHP|THB|TRY|VND|KRW|RUB|BRL|MXN|NZD|HKD|Rs\.?|RM|Rp)\b/i;

export function currencyFromText(text: string): string | undefined {
  for (const [pattern, code] of CURRENCY_TOKENS) {
    if (pattern.test(text)) return code;
  }
  return undefined;
}

/** Country-level fallback. Only ever consulted when the page itself is silent. */
export function currencyFromHostname(hostname: string): string | undefined {
  const byTld: Array<[RegExp, string]> = [
    [/\.co\.in$|\.in$/, 'INR'],
    [/\.co\.uk$|\.uk$/, 'GBP'],
    [/\.(de|fr|es|it|nl|be|ie|at|pt|fi|gr|eu)$/, 'EUR'],
    [/\.ca$/, 'CAD'],
    [/\.com\.au$|\.au$/, 'AUD'],
    [/\.co\.jp$|\.jp$/, 'JPY'],
    [/\.ae$/, 'AED'],
    [/\.com\.sg$|\.sg$/, 'SGD'],
    [/\.co\.za$/, 'ZAR'],
    [/\.com\.br$/, 'BRL'],
  ];
  for (const [pattern, code] of byTld) {
    if (pattern.test(hostname)) return code;
  }
  return undefined;
}

/**
 * Turn a numeric fragment into a number, working out which separator is the
 * decimal point:
 *
 *  - both `.` and `,` present -> the rightmost one is the decimal separator
 *  - one separator appearing more than once -> it groups thousands
 *  - one separator with exactly 3 digits after it -> thousands ("12,990")
 *  - one separator with 1-2 digits after it -> decimal ("45,50")
 */
export function parseAmount(raw: string): number | undefined {
  const match = raw.match(PRICE_PATTERN);
  if (!match) return undefined;

  let token = match[0].replace(/[\s']/g, '');
  const dots = (token.match(/\./g) ?? []).length;
  const commas = (token.match(/,/g) ?? []).length;

  if (dots && commas) {
    const decimalSep = token.lastIndexOf('.') > token.lastIndexOf(',') ? '.' : ',';
    const groupSep = decimalSep === '.' ? ',' : '.';
    token = token.split(groupSep).join('').replace(decimalSep, '.');
  } else if (dots || commas) {
    const sep = dots ? '.' : ',';
    const count = dots || commas;
    const tail = token.slice(token.lastIndexOf(sep) + 1);
    if (count > 1 || tail.length === 3) {
      token = token.split(sep).join('');
    } else {
      token = token.replace(sep, '.');
    }
  }

  const value = Number.parseFloat(token);
  return Number.isFinite(value) ? value : undefined;
}

/** Parse a full price string, including its currency when one is present. */
export function parsePrice(raw: unknown): ParsedPrice | undefined {
  if (typeof raw === 'number') {
    return Number.isFinite(raw) && raw > 0 ? { amount: raw } : undefined;
  }
  if (typeof raw !== 'string') return undefined;

  const text = raw.trim();
  if (!text) return undefined;

  const amount = parseAmount(text);
  if (amount === undefined || amount <= 0) return undefined;

  return { amount, currency: currencyFromText(text) };
}

/** Schema.org and embedded JSON express price as a bare number or a string. */
export function toAmount(raw: unknown): number | undefined {
  if (typeof raw === 'number') return Number.isFinite(raw) && raw > 0 ? raw : undefined;
  if (typeof raw === 'string') return parsePrice(raw)?.amount;
  return undefined;
}

export function currencySymbol(code?: string): string {
  if (!code) return '';
  return SYMBOLS[code.toUpperCase()] ?? `${code.toUpperCase()} `;
}

/** Locale-aware where it matters (INR groups as 12,990 rather than 12.990). */
export function formatPrice(amount?: number, currency?: string): string {
  if (amount === undefined || !Number.isFinite(amount)) return '—';
  const code = currency?.toUpperCase();
  if (code && /^[A-Z]{3}$/.test(code)) {
    try {
      return new Intl.NumberFormat(code === 'INR' ? 'en-IN' : undefined, {
        style: 'currency',
        currency: code,
        maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
      }).format(amount);
    } catch {
      // Unknown ISO code for this runtime - fall through to the manual format.
    }
  }
  const rounded = Number.isInteger(amount) ? amount.toString() : amount.toFixed(2);
  return `${currencySymbol(code)}${rounded}`;
}

export function discountPercentage(current?: number, original?: number): number | undefined {
  if (!current || !original || original <= current) return undefined;
  return Math.round(((original - current) / original) * 100);
}
