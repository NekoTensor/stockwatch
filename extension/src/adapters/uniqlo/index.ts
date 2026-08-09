/**
 * Uniqlo.
 *
 * Ships its product model in embedded JSON, which the generic embedded layer
 * finds by scoring. Only the brand and the E-prefixed product code are
 * store-specific.
 */

import { createStoreAdapter } from '../shared';

export const UniqloAdapter = createStoreAdapter({
  id: 'uniqlo',
  label: 'Uniqlo',
  domains: ['uniqlo.com'],
  brand: 'Uniqlo',
  idPattern: /\/products\/(E?\d{6,})/i,
  productUrlPattern: /\/products\/E?\d{6,}/i,
});
