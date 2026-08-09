/**
 * Zara.
 *
 * Zara publishes a complete schema.org Product with one Offer per size, so the
 * generic JSON-LD layer already does the heavy lifting. What it does not
 * publish is a brand — every product on zara.com is Zara, which the markup
 * treats as too obvious to state.
 */

import { createStoreAdapter } from '../shared';

export const ZaraAdapter = createStoreAdapter({
  id: 'zara',
  label: 'Zara',
  domains: ['zara.com'],
  brand: 'Zara',
  //: …/leather-effect-jacket-p07840321.html
  idPattern: /-p(\d{6,})\.html/i,
  productUrlPattern: /-p\d{6,}\.html/i,
});
