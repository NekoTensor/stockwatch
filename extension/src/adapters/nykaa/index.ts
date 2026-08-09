/**
 * Nykaa and Nykaa Fashion.
 *
 * Beauty products vary by *shade* rather than size, which the generic variant
 * detector already handles — `Shade 01` matches the variant token pattern and
 * is typed as a shade, not a size. Nothing store-specific is needed beyond the
 * product id.
 */

import { createStoreAdapter } from '../shared';

export const NykaaAdapter = createStoreAdapter({
  id: 'nykaafashion',
  label: 'Nykaa Fashion',
  domains: ['nykaafashion.com', 'nykaa.com'],
  idPattern: /\/p\/(\d{4,})/i,
  productUrlPattern: /\/p\/\d{4,}/i,
});
