/**
 * The generic adapter — the one that handles every store on the internet.
 *
 * Note what is *not* here: no selectors, no extraction, no per-store special
 * cases. All of that lives in the layered pipeline, which runs for every page
 * regardless of which adapter is chosen. This adapter's only job is to accept
 * any page and contribute the small amount of knowledge that can be derived
 * from a URL alone.
 *
 * If you are adding a store adapter, this file is the template: implement only
 * what your store does *differently*, and let the pipeline do the rest.
 */

import type { DetectionContext } from '../../lib/types';
import { looksLikeNonProductUrl, looksLikeProductUrl } from '../../lib/url';
import { findStoreDefinition } from '../../stores/registry';
import type { StoreAdapter } from '../types';

export const GenericAdapter: StoreAdapter = {
  id: 'generic',
  label: 'Generic',

  canHandle(): boolean {
    return true;
  },

  isProductPage(ctx: DetectionContext): boolean | undefined {
    // A known store's own URL shape is the strongest hint available here.
    const store = findStoreDefinition(ctx.hostname);
    if (store?.def.productUrlPatterns?.some((pattern) => pattern.test(ctx.url))) return true;

    if (looksLikeNonProductUrl(ctx.url)) return false;
    if (looksLikeProductUrl(ctx.url)) return true;

    // No opinion — let the content signals decide.
    return undefined;
  },
};
