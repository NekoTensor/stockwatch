/**
 * Myntra.
 *
 * A marketplace, so the brand comes from the product, never from the store —
 * this adapter deliberately sets no brand default. The whole product lives in
 * embedded state, which the generic layer finds by scoring; all that is
 * store-specific is the style id in the URL.
 */

import { createStoreAdapter } from '../shared';

export const MyntraAdapter = createStoreAdapter({
  id: 'myntra',
  label: 'Myntra',
  domains: ['myntra.com'],
  //: /jeans/roadster/roadster-men-blue-jeans/2296012/buy
  idPattern: /\/(\d{5,})\/buy/i,
  productUrlPattern: /\/\d{5,}\/buy/i,
});
