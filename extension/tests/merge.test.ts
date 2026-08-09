/**
 * Merge behaviour, tested directly.
 *
 * The most important assertion in this file is the last one: a layer that does
 * not know must never be allowed to turn into "out of stock".
 */

import { describe, expect, it } from 'vitest';

import { mergeCandidates, mergeVariantSets } from '../src/detection/merge';
import {
  availabilityFromFlag,
  availabilityFromSchema,
  availabilityFromText,
  mergeAvailability,
} from '../src/detection/util/availability';
import type { Candidate, Variant } from '../src/lib/types';

const variant = (name: string, availability: Variant['availability'], source: Variant['source']): Variant => ({
  id: name,
  name,
  type: 'size',
  availability,
  source,
});

describe('mergeVariantSets', () => {
  it('keeps the structured names and adopts availability from the DOM', () => {
    const merged = mergeVariantSets([
      {
        source: 'jsonld',
        variants: [variant('S', 'unknown', 'jsonld'), variant('M', 'unknown', 'jsonld')],
      },
      {
        source: 'dom',
        variants: [variant('s', 'in_stock', 'dom'), variant('M', 'out_of_stock', 'dom')],
      },
    ]);

    expect(merged.map((v) => v.name)).toEqual(['S', 'M']);
    expect(merged.find((v) => v.name === 'S')?.availability).toBe('in_stock');
    expect(merged.find((v) => v.name === 'M')?.availability).toBe('out_of_stock');
  });

  it('matches names across formatting differences', () => {
    const merged = mergeVariantSets([
      { source: 'jsonld', variants: [variant('UK 8', 'unknown', 'jsonld')] },
      { source: 'dom', variants: [variant('uk-8', 'out_of_stock', 'dom')] },
    ]);
    expect(merged).toHaveLength(1);
    expect(merged[0].availability).toBe('out_of_stock');
  });

  it('prefers the set that actually knows about stock', () => {
    const merged = mergeVariantSets([
      { source: 'embedded', variants: [variant('S', 'unknown', 'embedded'), variant('M', 'unknown', 'embedded')] },
      { source: 'dom', variants: [variant('S', 'in_stock', 'dom'), variant('M', 'out_of_stock', 'dom')] },
    ]);
    expect(merged.every((v) => v.availability !== 'unknown')).toBe(true);
  });
});

describe('mergeCandidates', () => {
  const jsonld: Candidate = {
    source: 'jsonld',
    data: { productName: 'Wool Coat', currentPrice: 15990, currency: 'INR' },
  };
  const dom: Candidate = {
    source: 'dom',
    data: { productName: 'Wool Coat - Buy Online', currentPrice: 11990, brand: 'Northbound' },
  };

  it('resolves each field independently by trust', () => {
    const merged = mergeCandidates([dom, jsonld]);
    expect(merged.data.productName).toBe('Wool Coat');
    expect(merged.data.currentPrice).toBe(15990);
    expect(merged.data.brand).toBe('Northbound'); // only the DOM had it
    expect(merged.provenance.productName).toBe('jsonld');
    expect(merged.provenance.brand).toBe('dom');
  });

  it('drops an "original price" that is not actually higher', () => {
    const merged = mergeCandidates([
      { source: 'dom', data: { currentPrice: 1299, originalPrice: 899 } },
    ]);
    expect(merged.data.originalPrice).toBeUndefined();
    expect(merged.data.discountPercentage).toBeUndefined();
  });
});

describe('availability is three-valued on purpose', () => {
  it('maps schema.org vocabulary', () => {
    expect(availabilityFromSchema('https://schema.org/InStock')).toBe('in_stock');
    expect(availabilityFromSchema('http://schema.org/OutOfStock')).toBe('out_of_stock');
    expect(availabilityFromSchema('SoldOut')).toBe('out_of_stock');
  });

  it('checks sold-out phrases before the word "available"', () => {
    expect(availabilityFromText('Notify me when available')).toBe('out_of_stock');
    expect(availabilityFromText('Add to bag')).toBe('in_stock');
  });

  it('treats a zero count as sold out and a missing count as unknown', () => {
    expect(availabilityFromFlag(0)).toBe('out_of_stock');
    expect(availabilityFromFlag(4)).toBe('in_stock');
    expect(availabilityFromFlag(undefined)).toBe('unknown');
    expect(availabilityFromFlag(null)).toBe('unknown');
  });

  it('never lets "we do not know" become "out of stock"', () => {
    expect(availabilityFromSchema('SomethingWeHaveNeverSeen')).toBe('unknown');
    expect(availabilityFromText('')).toBe('unknown');
    expect(availabilityFromText('Ships from and sold by Example')).toBe('unknown');
    expect(mergeAvailability('unknown', 'unknown')).toBe('unknown');
    expect(mergeAvailability('unknown', 'in_stock')).toBe('in_stock');
    expect(mergeAvailability('out_of_stock', 'unknown')).toBe('out_of_stock');
  });

  it('resolves a genuine disagreement optimistically', () => {
    // A missed restock costs the user the item; a spurious ping costs a glance.
    expect(mergeAvailability('out_of_stock', 'in_stock')).toBe('in_stock');
  });
});
