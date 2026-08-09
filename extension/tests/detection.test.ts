/**
 * End-to-end pipeline tests.
 *
 * Each fixture is a *shape* of page rather than a copy of one store, because
 * the claim being tested is that detection is store-independent. If these pass,
 * any store publishing data the same way works — named adapter or not.
 */

import { describe, expect, it } from 'vitest';

import { runDetection } from '../src/detection/pipeline';
import { contextFromFixture, contextFromHtml } from './helpers';

describe('JSON-LD product page (one offer per size)', () => {
  const result = runDetection(
    contextFromFixture('jsonld-apparel.html', 'https://www.zara.com/in/en/leather-effect-jacket-p07840321.html'),
  );

  it('detects the product with high confidence', () => {
    expect(result.status).toBe('detected');
    expect(result.confidence).toBeGreaterThanOrEqual(70);
  });

  it('reads the identity fields from structured data', () => {
    expect(result.product?.productName).toBe('Leather Effect Jacket');
    expect(result.product?.brand).toBe('Zara');
    expect(result.product?.sku).toBe('07840321-800');
    expect(result.provenance.productName).toBe('jsonld');
  });

  it('names the store from the hostname', () => {
    expect(result.product?.store).toBe('Zara');
    expect(result.product?.storeId).toBe('zara');
  });

  it('reads price and currency', () => {
    expect(result.product?.currentPrice).toBe(12990);
    expect(result.product?.currency).toBe('INR');
  });

  it('turns the offers into variants with per-size availability', () => {
    const variants = result.product?.variants ?? [];
    expect(variants.map((v) => v.name)).toEqual(['S', 'M', 'L', 'XL']);
    expect(variants.find((v) => v.name === 'S')?.availability).toBe('in_stock');
    expect(variants.find((v) => v.name === 'M')?.availability).toBe('out_of_stock');
    expect(variants.filter((v) => v.availability === 'out_of_stock')).toHaveLength(3);
  });

  it('resolves relative image URLs against the page', () => {
    expect(result.product?.imageUrl).toMatch(/^https:\/\//);
  });

  it('ignores prices from the recommendations rail', () => {
    expect(result.product?.currentPrice).not.toBe(7590);
  });
});

describe('OpenGraph + DOM page (no JSON-LD)', () => {
  const result = runDetection(
    contextFromFixture('og-and-dom.html', 'https://www2.hm.com/en_in/productpage.1234567001.html'),
  );

  it('detects the product', () => {
    expect(result.status).toBe('detected');
    expect(result.product?.productName).toBe('Oversized Hoodie');
    expect(result.product?.store).toBe('H&M');
  });

  it('takes the price from OpenGraph and the old price from the DOM', () => {
    expect(result.product?.currentPrice).toBe(1999);
    expect(result.product?.currency).toBe('INR');
    expect(result.product?.originalPrice).toBe(2999);
    expect(result.product?.discountPercentage).toBe(33);
  });

  it('reads sizes and their disabled state out of the rendered widget', () => {
    const variants = result.product?.variants ?? [];
    expect(variants.map((v) => v.name)).toEqual(['XS', 'S', 'M', 'L', 'XL']);
    expect(variants.find((v) => v.name === 'M')?.availability).toBe('out_of_stock');
    expect(variants.find((v) => v.name === 'XL')?.availability).toBe('out_of_stock');
    expect(variants.find((v) => v.name === 'S')?.availability).toBe('in_stock');
  });

  it('classifies the variants as sizes', () => {
    expect(result.product?.variants.every((v) => v.type === 'size')).toBe(true);
  });
});

describe('client-rendered page (product only exists in embedded JSON)', () => {
  const result = runDetection(
    contextFromFixture(
      'embedded-state.html',
      'https://www.myntra.com/jeans/roadster/roadster-men-blue-jeans/2296012/buy',
    ),
  );

  it('finds the product inside the state blob', () => {
    expect(result.status).toBe('detected');
    expect(result.product?.productName).toBe('Roadster Men Blue Slim Fit Jeans');
    expect(result.product?.brand).toBe('Roadster');
    expect(result.provenance.productName).toBe('embedded');
  });

  it('prefers the selling price over the MRP', () => {
    expect(result.product?.currentPrice).toBe(1149);
    expect(result.product?.originalPrice).toBe(2299);
    expect(result.product?.discountPercentage).toBe(50);
  });

  it('reads waist sizes and treats a zero count as sold out', () => {
    const variants = result.product?.variants ?? [];
    expect(variants.map((v) => v.name)).toEqual(['28', '30', '32', '34', '36']);
    expect(variants.find((v) => v.name === '30')?.availability).toBe('out_of_stock');
    expect(variants.find((v) => v.name === '32')?.availability).toBe('in_stock');
  });
});

describe('microdata page', () => {
  const result = runDetection(contextFromFixture('microdata.html', 'https://www.example-outdoors.fr/p/trail-shoes-8845'));

  it('detects the product', () => {
    expect(result.status).toBe('detected');
    expect(result.product?.productName).toBe('Kalenji Trail Running Shoes');
    expect(result.product?.sku).toBe('TRL-8845');
  });

  it('does not mistake the nested review title for the product name', () => {
    expect(result.product?.productName).not.toContain('Best shoes');
  });

  it('reads the offer price and currency', () => {
    expect(result.product?.currentPrice).toBe(59.99);
    expect(result.product?.currency).toBe('EUR');
  });

  it('reads shoe sizes and aria-disabled state', () => {
    const variants = result.product?.variants ?? [];
    expect(variants.map((v) => v.name)).toEqual(['UK 7', 'UK 8', 'UK 9', 'UK 10']);
    expect(variants.find((v) => v.name === 'UK 9')?.availability).toBe('out_of_stock');
  });

  it('names an unknown store from its domain', () => {
    expect(result.product?.store).toBe('Example Outdoors');
    expect(result.product?.storeId).toBe('generic');
  });
});

describe('unknown store with no structured data at all', () => {
  const result = runDetection(
    contextFromFixture('dom-only.html', 'https://www.studiobeauty.in/product/velvet-matte-lipstick'),
  );

  it('still detects the product', () => {
    expect(result.status).toBe('detected');
    expect(result.product?.productName).toBe('Velvet Matte Lipstick');
    expect(result.provenance.productName).toBe('dom');
  });

  it('picks the sale price and the struck-through MRP correctly', () => {
    expect(result.product?.currentPrice).toBe(899);
    expect(result.product?.originalPrice).toBe(1299);
  });

  it('reads shades as variants, not sizes', () => {
    const variants = result.product?.variants ?? [];
    expect(variants.map((v) => v.name)).toEqual(['Shade 01', 'Shade 02', 'Shade 03', 'Shade 04']);
    expect(variants.find((v) => v.name === 'Shade 03')?.availability).toBe('out_of_stock');
    expect(variants[0]?.type).toBe('shade');
  });
});

describe('category listing page', () => {
  const result = runDetection(contextFromFixture('listing-page.html', 'https://www.example-store.com/women/jackets'));

  it('refuses to call a grid of products a product', () => {
    expect(result.status).toBe('not_a_product');
    expect(result.product).toBeUndefined();
  });
});

describe('page globals harvested from the MAIN world', () => {
  // Google Tag Manager's ecommerce payload — present on a large share of stores
  // and never referenced by name anywhere in the detector.
  const dataLayer = [
    { event: 'gtm.js' },
    {
      event: 'productDetail',
      ecommerce: {
        detail: {
          products: [
            {
              name: 'Merino Wool Crew Neck',
              id: 'MW-2231',
              price: '4499',
              brand: 'Northbound',
              category: 'Knitwear',
              variant: 'Charcoal',
            },
          ],
        },
      },
    },
  ];

  const result = runDetection(
    contextFromHtml(
      '<html><head><title>Merino Wool Crew Neck</title></head><body><main><h1>Merino Wool Crew Neck</h1><button>Add to cart</button></main></body></html>',
      'https://www.northbound.example/p/merino-crew-2231',
      { dataLayer },
    ),
  );

  it('reads the product out of the analytics payload', () => {
    expect(result.product?.productName).toBe('Merino Wool Crew Neck');
    expect(result.product?.brand).toBe('Northbound');
    expect(result.product?.currentPrice).toBe(4499);
  });
});

describe('honesty about what was not found', () => {
  const result = runDetection(
    contextFromHtml(
      `<html><head>
         <meta property="og:type" content="product" />
         <meta property="og:title" content="Handwoven Cotton Throw" />
         <meta property="og:image" content="https://example.com/throw.jpg" />
       </head><body><main><h1>Handwoven Cotton Throw</h1><p>Made in Kerala.</p></main></body></html>`,
      'https://www.smallweaver.example/product/handwoven-throw',
    ),
  );

  it('reports a partial detection rather than a fake one', () => {
    expect(['partial', 'detected']).toContain(result.status);
    expect(result.product?.currentPrice).toBeUndefined();
    expect(result.missing).toContain('Price');
    expect(result.missing).toContain('Variants');
  });

  it('never claims stock it could not verify', () => {
    expect(result.product?.availability).toBe('unknown');
  });
});
