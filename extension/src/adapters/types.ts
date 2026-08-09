/**
 * The store adapter contract.
 *
 * The central rule of this project: **an adapter is an enhancement, never a
 * requirement.** The generic pipeline runs first and produces a complete
 * result on its own; an adapter is then given what was found and may fill in
 * the gaps its store is known to leave.
 *
 * That inversion is what stops the codebase turning into nine copies of the
 * same extraction logic, and it is why an unsupported store still works.
 */

import type { DetectionContext, PriceData, ProductData, StockStatus, Variant } from '../lib/types';

export interface AdapterInput {
  ctx: DetectionContext;
  /** Everything the generic layers already agreed on. Read-only. */
  base: Readonly<Partial<ProductData>>;
}

export interface StoreAdapter {
  /** Matches the store id in the registry, e.g. "zara". */
  id: string;
  label: string;

  /** Does this adapter want the page? Checked against hostname and URL. */
  canHandle(ctx: DetectionContext): boolean;

  /**
   * Store-specific fields only. Return `null` when the generic result is
   * already good enough — that is the expected answer most of the time.
   */
  detectProduct?(input: AdapterInput): Partial<ProductData> | null;
  detectVariants?(input: AdapterInput): Variant[] | null;
  detectAvailability?(input: AdapterInput): StockStatus | null;
  detectPrice?(input: AdapterInput): PriceData | null;

  /** Store-specific "is this a product page" knowledge. */
  isProductPage?(ctx: DetectionContext): boolean | undefined;

  /**
   * When true, this adapter's fields replace the generic ones instead of only
   * filling holes. Reserve it for stores that are known to publish misleading
   * structured data (e.g. a stale JSON-LD price).
   */
  authoritative?: boolean;
}
