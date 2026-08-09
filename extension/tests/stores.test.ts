import { describe, expect, it } from 'vitest';

import { identifyStore, prettifyHostname } from '../src/stores/registry';
import { cleanUrl, isRestrictedPage, looksLikeNonProductUrl, looksLikeProductUrl, productIdFromUrl } from '../src/lib/url';

describe('identifyStore', () => {
  it('names the stores we know, across subdomains', () => {
    expect(identifyStore('www.zara.com').name).toBe('Zara');
    expect(identifyStore('www2.hm.com').name).toBe('H&M');
    expect(identifyStore('m.myntra.com').name).toBe('Myntra');
    expect(identifyStore('nykaafashion.com').name).toBe('Nykaa Fashion');
    expect(identifyStore('www.ajio.com').id).toBe('ajio');
  });

  it('distinguishes Amazon storefronts by region', () => {
    expect(identifyStore('amazon.in').name).toBe('Amazon India');
    expect(identifyStore('www.amazon.co.uk').name).toBe('Amazon UK');
    expect(identifyStore('amazon.com').name).toBe('Amazon');
  });

  it('prefers the most specific domain match', () => {
    expect(identifyStore('shop.mango.com').id).toBe('mango');
    expect(identifyStore('www.adidas.co.in').id).toBe('adidas');
  });

  it('still names a store it has never seen', () => {
    const unknown = identifyStore('shop.some-boutique.co.uk');
    expect(unknown.known).toBe(false);
    expect(unknown.id).toBe('generic');
    expect(unknown.name).toBe('Some Boutique');
  });
});

describe('prettifyHostname', () => {
  it('strips TLDs and generic subdomains', () => {
    expect(prettifyHostname('example.com')).toBe('Example');
    expect(prettifyHostname('store.velvet-lane.in')).toBe('Velvet Lane');
  });
});

describe('URL helpers', () => {
  it('strips campaign parameters but keeps product selectors', () => {
    const cleaned = cleanUrl(
      'https://www.myntra.com/jeans/roadster/x/2296012/buy?utm_source=email&utm_campaign=sale&size=32',
    );
    expect(cleaned).toContain('size=32');
    expect(cleaned).not.toContain('utm_source');
    expect(cleaned).not.toContain('utm_campaign');
  });

  it("removes Amazon's navigation-history path segment but keeps the ASIN", () => {
    const cleaned = cleanUrl('https://www.amazon.in/dp/B0CHX1W1XY/ref=sr_1_3?pd_rd_i=abc&psc=1');
    expect(cleaned).toBe('https://www.amazon.in/dp/B0CHX1W1XY');
    expect(cleaned).not.toContain('/ref=');
  });

  it('pulls the product id out of the address', () => {
    expect(productIdFromUrl('https://www.amazon.in/dp/B0CHX1W1XY')).toBe('B0CHX1W1XY');
    expect(productIdFromUrl('https://www.zara.com/in/en/jacket-p07840321.html')).toBe('07840321');
    expect(productIdFromUrl('https://www2.hm.com/en_in/productpage.1234567001.html')).toBe('1234567001');
  });

  it('separates product URLs from listing URLs', () => {
    expect(looksLikeProductUrl('https://www.ajio.com/p/441088931')).toBe(true);
    expect(looksLikeNonProductUrl('https://www.ajio.com/')).toBe(true);
    expect(looksLikeNonProductUrl('https://www.ajio.com/search?q=jeans')).toBe(true);
  });

  it('refuses pages an extension must not touch', () => {
    expect(isRestrictedPage('chrome://extensions')).toBe(true);
    expect(isRestrictedPage('https://chromewebstore.google.com/detail/abc')).toBe(true);
    expect(isRestrictedPage(undefined)).toBe(true);
    expect(isRestrictedPage('https://www.zara.com/in/en/x-p1.html')).toBe(false);
  });
});
