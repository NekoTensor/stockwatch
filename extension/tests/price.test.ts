import { describe, expect, it } from 'vitest';

import {
  currencyFromHostname,
  currencyFromText,
  discountPercentage,
  formatPrice,
  parseAmount,
  parsePrice,
} from '../src/lib/price';

describe('parseAmount', () => {
  it('reads Indian grouping without inventing decimals', () => {
    expect(parseAmount('12,990')).toBe(12990);
    expect(parseAmount('1,24,999')).toBe(124999);
  });

  it('reads US grouping with decimals', () => {
    expect(parseAmount('1,299.99')).toBe(1299.99);
  });

  it('reads European grouping where the roles are swapped', () => {
    expect(parseAmount('1.299,99')).toBe(1299.99);
    expect(parseAmount('1.500')).toBe(1500);
  });

  it('treats a lone separator with two trailing digits as a decimal point', () => {
    expect(parseAmount('59,99')).toBe(59.99);
    expect(parseAmount('59.99')).toBe(59.99);
  });

  it('handles spaces used as thousands separators', () => {
    expect(parseAmount('2 499')).toBe(2499);
  });

  it('returns undefined when there is no number', () => {
    expect(parseAmount('Sold out')).toBeUndefined();
  });
});

describe('parsePrice', () => {
  it('extracts amount and currency together', () => {
    expect(parsePrice('₹12,990')).toEqual({ amount: 12990, currency: 'INR' });
    expect(parsePrice('Rs. 2,499/-')).toEqual({ amount: 2499, currency: 'INR' });
    expect(parsePrice('$1,299.99')).toEqual({ amount: 1299.99, currency: 'USD' });
    expect(parsePrice('59,99 €')).toEqual({ amount: 59.99, currency: 'EUR' });
  });

  it('prefers the specific dollar variant over bare USD', () => {
    expect(parsePrice('A$149.00')?.currency).toBe('AUD');
  });

  it('rejects zero and negative amounts', () => {
    expect(parsePrice('₹0')).toBeUndefined();
    expect(parsePrice('')).toBeUndefined();
  });

  it('ignores surrounding prose', () => {
    expect(parsePrice('MRP ₹3,999 (incl. of all taxes)')?.amount).toBe(3999);
  });
});

describe('currency inference', () => {
  it('reads currency words as well as symbols', () => {
    expect(currencyFromText('INR 4,500')).toBe('INR');
    expect(currencyFromText('4500 rupees')).toBe('INR');
  });

  it('falls back to the country of the domain', () => {
    expect(currencyFromHostname('myntra.com')).toBeUndefined();
    expect(currencyFromHostname('amazon.in')).toBe('INR');
    expect(currencyFromHostname('asos.co.uk')).toBe('GBP');
  });
});

describe('formatting', () => {
  it('groups INR the Indian way', () => {
    expect(formatPrice(124999, 'INR')).toContain('1,24,999');
  });

  it('degrades gracefully without a currency', () => {
    expect(formatPrice(1200)).toBe('1200');
    expect(formatPrice(undefined)).toBe('—');
  });
});

describe('discountPercentage', () => {
  it('computes the saving', () => {
    expect(discountPercentage(899, 1299)).toBe(31);
  });

  it('refuses to report a negative discount', () => {
    expect(discountPercentage(1299, 899)).toBeUndefined();
    expect(discountPercentage(1299, 1299)).toBeUndefined();
  });
});
