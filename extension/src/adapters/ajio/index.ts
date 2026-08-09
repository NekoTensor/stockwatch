/**
 * AJIO.
 *
 * Marketplace, so no brand default. Renders client-side from a preloaded state
 * object, which the generic embedded layer reads.
 */

import { createStoreAdapter } from '../shared';

export const AjioAdapter = createStoreAdapter({
  id: 'ajio',
  label: 'AJIO',
  domains: ['ajio.com'],
  idPattern: /\/p\/(\d{6,})/i,
  productUrlPattern: /\/p\/\d{6,}/i,
});
