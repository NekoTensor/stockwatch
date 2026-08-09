/**
 * Nike.
 *
 * The style-colour code in the URL (e.g. `CN8490-002`) identifies the exact
 * colourway, which matters: two colourways of the same shoe have independent
 * size availability and must not be tracked as one product.
 */

import { createStoreAdapter } from '../shared';

export const NikeAdapter = createStoreAdapter({
  id: 'nike',
  label: 'Nike',
  domains: ['nike.com'],
  brand: 'Nike',
  //: /t/air-max-90-shoes/CN8490-002
  idPattern: /\/t\/[^/]+\/([A-Z0-9]{6,}-[A-Z0-9]{3,})/i,
  productUrlPattern: /\/t\/[^/]+\/[A-Z0-9]{6,}/i,
});
