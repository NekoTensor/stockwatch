/**
 * Adidas.
 *
 * Like Nike, the article code in the URL is colourway-specific
 * (`…/ultraboost-light-shoes/HQ6339.html`).
 */

import { createStoreAdapter } from '../shared';

export const AdidasAdapter = createStoreAdapter({
  id: 'adidas',
  label: 'Adidas',
  domains: ['adidas.com', 'adidas.co.in', 'adidas.co.uk', 'adidas.de', 'adidas.ae'],
  brand: 'Adidas',
  idPattern: /\/([A-Z]{2}\d{4})\.html/i,
  productUrlPattern: /\/[A-Z]{2}\d{4}\.html/i,
});
