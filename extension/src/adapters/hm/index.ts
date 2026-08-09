/**
 * H&M.
 *
 * No JSON-LD Product on most regional sites; OpenGraph carries the name, image
 * and price, and the size widget is the only source of per-size stock. Both are
 * generic-layer concerns — this adapter only names the brand and reads the
 * article number out of the URL.
 */

import { createStoreAdapter } from '../shared';

export const HmAdapter = createStoreAdapter({
  id: 'hm',
  label: 'H&M',
  domains: ['hm.com', 'www2.hm.com'],
  brand: 'H&M',
  //: …/productpage.0713986001.html
  idPattern: /productpage\.(\d{6,})\.html/i,
  productUrlPattern: /productpage\.\d{6,}\.html/i,
});
