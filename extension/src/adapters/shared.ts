/**
 * Helpers shared by the store adapters.
 *
 * Everything here is about *matching* and *small store facts* — never about
 * extraction. If a helper here starts doing real parsing, it belongs in
 * `detection/layers/`, where every store benefits from it.
 */

import type { DetectionContext, ProductData } from '../lib/types';
import type { AdapterInput, StoreAdapter } from './types';

export function matchesHost(hostname: string, domains: string[]): boolean {
  return domains.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`));
}

export interface SingleBrandOptions {
  id: string;
  label: string;
  domains: string[];
  /** Stores that sell only their own label rarely publish a `brand` anywhere. */
  brand?: string;
  /** First capture group becomes the product id. */
  idPattern?: RegExp;
  /** When set, a URL match is treated as a definite product page. */
  productUrlPattern?: RegExp;
}

/**
 * Builds an adapter that contributes a brand default and a product id.
 *
 * This covers most of what a store-specific adapter legitimately knows. Stores
 * that need more (Amazon) implement the interface directly.
 */
export function createStoreAdapter(options: SingleBrandOptions): StoreAdapter {
  const { id, label, domains, brand, idPattern, productUrlPattern } = options;

  return {
    id,
    label,

    canHandle(ctx: DetectionContext): boolean {
      return matchesHost(ctx.hostname, domains);
    },

    detectProduct({ ctx, base }: AdapterInput): Partial<ProductData> | null {
      const contribution: Partial<ProductData> = {};

      if (brand && !base.brand) contribution.brand = brand;

      if (idPattern && !base.productId) {
        const match = ctx.url.match(idPattern);
        if (match?.[1]) contribution.productId = match[1];
      }

      return Object.keys(contribution).length ? contribution : null;
    },

    isProductPage(ctx: DetectionContext): boolean | undefined {
      if (!productUrlPattern) return undefined;
      return productUrlPattern.test(ctx.url) ? true : undefined;
    },
  };
}
