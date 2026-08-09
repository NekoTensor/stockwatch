/**
 * The product, presented the way the shop presents it: image first, then a
 * quiet block of type. Everything that is chrome is uppercase and grey, so the
 * product name is the only normal-case text and reads as the subject.
 */

import { useState } from 'react';

import { formatPrice } from '../../lib/price';
import { normaliseKey } from '../../lib/text';
import type { ProductData } from '../../lib/types';
import { StockLabel } from './ui';

export function ProductHero({ product }: { product: ProductData }) {
  const [failed, setFailed] = useState(false);
  const showImage = Boolean(product.imageUrl) && !failed;

  // On a single-brand store the brand and the store are the same thing said
  // twice ("ZARA / Zara"), so only show the brand when it adds something.
  const showBrand =
    Boolean(product.brand) && normaliseKey(product.brand ?? '') !== normaliseKey(product.store);

  return (
    <div className="sw-fade">
      <div
        className="relative w-full overflow-hidden"
        style={{ height: 268, background: 'var(--sw-surface)' }}
      >
        {showImage ? (
          <img
            src={product.imageUrl}
            alt={product.productName ?? 'Product'}
            className="h-full w-full object-cover"
            onError={() => setFailed(true)}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <span className="sw-label">No image</span>
          </div>
        )}
      </div>

      <div className="px-5 pb-4 pt-4">
        <div className="sw-label mb-2 flex items-center gap-2">
          <span className="truncate">{product.store}</span>
          {showBrand ? (
            <>
              <span style={{ color: 'var(--sw-line)' }}>|</span>
              <span className="truncate">{product.brand}</span>
            </>
          ) : null}
        </div>

        <h1 className="text-[15px] font-normal leading-snug">
          {product.productName ?? 'Unnamed product'}
        </h1>

        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {product.currentPrice !== undefined ? (
            <span className={`sw-price ${product.discountPercentage ? 'sw-price-sale' : ''}`}>
              {formatPrice(product.currentPrice, product.currency)}
            </span>
          ) : (
            <span className="sw-label">Price not detected</span>
          )}

          {product.originalPrice !== undefined ? (
            <span className="sw-price-was">{formatPrice(product.originalPrice, product.currency)}</span>
          ) : null}

          {product.discountPercentage ? (
            <span className="sw-label" style={{ color: 'var(--sw-sale)' }}>
              −{product.discountPercentage}%
            </span>
          ) : null}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1">
          <StockLabel status={product.availability} />
          {product.category ? <span className="sw-label truncate">{product.category}</span> : null}
        </div>
      </div>
    </div>
  );
}
