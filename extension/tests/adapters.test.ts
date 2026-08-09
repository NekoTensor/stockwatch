/**
 * Store adapters.
 *
 * The property under test throughout is the same: an adapter **fills gaps**. It
 * must never overwrite something the generic layers already established, and
 * removing it must never stop a page from being detected at all.
 */

import { describe, expect, it } from 'vitest';

import { registry } from '../src/adapters/registry';
import { runDetection } from '../src/detection/pipeline';
import { contextFromFixture, contextFromHtml } from './helpers';

describe('adapter resolution', () => {
  const cases: Array<[string, string]> = [
    ['https://www.zara.com/in/en/jacket-p07840321.html', 'zara'],
    ['https://www2.hm.com/en_in/productpage.1234567001.html', 'hm'],
    ['https://www.myntra.com/jeans/x/2296012/buy', 'myntra'],
    ['https://www.ajio.com/p/441088931', 'ajio'],
    ['https://www.nykaafashion.com/x/p/12345', 'nykaafashion'],
    ['https://www.amazon.in/dp/B0CHX1W1XY', 'amazon'],
    ['https://www.nike.com/t/air-max-90-shoes/CN8490-002', 'nike'],
    ['https://www.adidas.co.in/ultraboost/HQ6339.html', 'adidas'],
    ['https://www.uniqlo.com/in/en/products/E453056-000', 'uniqlo'],
    ['https://www.some-unknown-boutique.example/product/thing', 'generic'],
  ];

  it.each(cases)('resolves %s to the %s adapter', (url, expected) => {
    const ctx = contextFromHtml('<html><body></body></html>', url);
    expect(registry.resolve(ctx).id).toBe(expected);
  });

  it('registers every adapter exactly once', () => {
    const ids = registry.list().map((adapter) => adapter.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('single-brand adapters', () => {
  it('supplies the brand Zara never states, without touching anything else', () => {
    const result = runDetection(
      contextFromFixture('jsonld-apparel.html', 'https://www.zara.com/in/en/jacket-p07840321.html'),
    );

    expect(result.adapterId).toBe('zara');
    expect(result.product?.brand).toBe('Zara');
    // The JSON-LD values must survive untouched.
    expect(result.product?.productName).toBe('Leather Effect Jacket');
    expect(result.provenance.productName).toBe('jsonld');
    expect(result.product?.currentPrice).toBe(12990);
  });

  it('reads the article number out of an H&M URL', () => {
    const result = runDetection(
      contextFromFixture('og-and-dom.html', 'https://www2.hm.com/en_in/productpage.1234567001.html'),
    );

    expect(result.adapterId).toBe('hm');
    expect(result.product?.productId).toBe('1234567001');
    expect(result.product?.brand).toBe('H&M');
  });

  it('does not invent a brand on a marketplace', () => {
    const result = runDetection(
      contextFromFixture('embedded-state.html', 'https://www.myntra.com/jeans/x/2296012/buy'),
    );

    expect(result.adapterId).toBe('myntra');
    // Roadster is the brand; Myntra is the shop. Confusing the two would be
    // wrong on every marketplace listing.
    expect(result.product?.brand).toBe('Roadster');
  });
});

describe('Amazon adapter', () => {
  const result = runDetection(contextFromFixture('amazon-like.html', 'https://www.amazon.in/dp/B0CHX1W1XY'));

  it('detects a page with no structured data at all', () => {
    expect(result.status).toBe('detected');
    expect(result.adapterId).toBe('amazon');
    expect(result.product?.store).toBe('Amazon India');
  });

  it('reads the title and cleans up the byline into a brand', () => {
    expect(result.product?.productName).toBe('Acme Studio Wireless Headphones (Midnight Black)');
    expect(result.product?.brand).toBe('Acme');
  });

  it('reads the price and the struck-through list price', () => {
    expect(result.product?.currentPrice).toBe(8499);
    expect(result.product?.originalPrice).toBe(12999);
    expect(result.product?.currency).toBe('INR');
    expect(result.product?.discountPercentage).toBe(35);
  });

  it('takes the ASIN from the URL', () => {
    expect(result.product?.productId).toBe('B0CHX1W1XY');
  });

  it('reads the twister variants and their unavailable state', () => {
    const variants = result.product?.variants ?? [];
    expect(variants.map((variant) => variant.name)).toEqual(['Standard', 'Pro', 'Max']);
    expect(variants.find((variant) => variant.name === 'Max')?.availability).toBe('out_of_stock');
    expect(variants.find((variant) => variant.name === 'Pro')?.availability).toBe('in_stock');
  });
});

describe('adapters are an enhancement, not a requirement', () => {
  it('detects an Amazon-shaped page even when no adapter claims it', () => {
    // Same markup, a hostname no adapter matches: the generic pipeline alone
    // still has to find the product.
    const result = runDetection(
      contextFromFixture('amazon-like.html', 'https://www.some-marketplace.example/dp/B0CHX1W1XY'),
    );

    expect(result.adapterId).toBe('generic');
    expect(result.product?.productName).toContain('Acme Studio Wireless Headphones');
    expect(result.product?.currentPrice).toBe(8499);
  });
});
