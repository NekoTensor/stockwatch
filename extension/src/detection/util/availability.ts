/**
 * Everything that turns a store's idea of "can I buy this" into a `StockStatus`.
 *
 * The governing rule of this file: **absence of evidence is not evidence of
 * absence.** Anything we do not positively recognise returns `unknown`, never
 * `out_of_stock`. A tracker that guesses "sold out" wakes users up at 3am for
 * a restock that never happened.
 */

import type { StockStatus } from '../../lib/types';

/** schema.org ItemAvailability, with and without the URL prefix. */
const SCHEMA_IN_STOCK = /(InStock|OnlineOnly|InStoreOnly|LimitedAvailability|PreOrder|PreSale)$/i;
const SCHEMA_OUT_OF_STOCK = /(OutOfStock|SoldOut|Discontinued|BackOrder)$/i;

export function availabilityFromSchema(value: unknown): StockStatus {
  if (typeof value !== 'string') return 'unknown';
  const token = value.trim();
  if (!token) return 'unknown';
  if (SCHEMA_OUT_OF_STOCK.test(token)) return 'out_of_stock';
  if (SCHEMA_IN_STOCK.test(token)) return 'in_stock';
  return availabilityFromText(token);
}

/**
 * Out-of-stock phrases are checked first on purpose: "notify me when this is
 * available again" contains the word "available".
 */
const OUT_OF_STOCK_TEXT =
  /\b(out of stock|sold out|currently unavailable|temporarily unavailable|not available|unavailable|notify me|email me when|coming soon|back in stock soon|agotado|epuise|ausverkauft|non disponibile|esgotado)\b/i;

const IN_STOCK_TEXT =
  /\b(in stock|add to (cart|bag|basket)|buy (it )?now|add to cart|available now|ready to ship|en stock|disponible|auf lager)\b/i;

export function availabilityFromText(text: string | undefined | null): StockStatus {
  if (!text) return 'unknown';
  if (OUT_OF_STOCK_TEXT.test(text)) return 'out_of_stock';
  if (IN_STOCK_TEXT.test(text)) return 'in_stock';
  return 'unknown';
}

/**
 * Booleans, counts and the string flags embedded JSON uses. `0` means sold
 * out; `undefined` means we simply were not told.
 */
export function availabilityFromFlag(value: unknown): StockStatus {
  if (value === undefined || value === null) return 'unknown';
  if (typeof value === 'boolean') return value ? 'in_stock' : 'out_of_stock';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return 'unknown';
    return value > 0 ? 'in_stock' : 'out_of_stock';
  }
  if (typeof value === 'string') {
    const token = value.trim().toLowerCase();
    if (!token) return 'unknown';
    if (['true', 'yes', 'y', '1', 'available', 'instock', 'in_stock'].includes(token)) return 'in_stock';
    if (['false', 'no', 'n', '0', 'unavailable', 'outofstock', 'out_of_stock'].includes(token)) return 'out_of_stock';
    return availabilityFromSchema(token);
  }
  return 'unknown';
}

/** Invert a flag that is phrased negatively (`outOfStock: true`). */
export function availabilityFromNegativeFlag(value: unknown): StockStatus {
  const positive = availabilityFromFlag(value);
  if (positive === 'in_stock') return 'out_of_stock';
  if (positive === 'out_of_stock') return 'in_stock';
  return 'unknown';
}

/**
 * Combine what several layers said about the same thing. A confident answer
 * beats `unknown`; genuine disagreement resolves to `in_stock`, because the
 * cost of a false "back in stock" ping is far lower than never telling the
 * user their size returned.
 */
export function mergeAvailability(a: StockStatus, b: StockStatus): StockStatus {
  if (a === b) return a;
  if (a === 'unknown') return b;
  if (b === 'unknown') return a;
  return 'in_stock';
}
