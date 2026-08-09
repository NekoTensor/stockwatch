/**
 * A tracked product, as a shop would show it: image first, type quiet.
 *
 * Actions live behind a hover reveal so a wall of cards stays calm; on touch
 * they are always visible, because there is no hover to reveal them with.
 */

import { useState } from 'react';

import type { TrackedProductOut } from '../../lib/api';
import { formatPrice } from '../../lib/price';
import { StockLabel } from '../../popup/components/ui';

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/**
 * The whole phrase, not a fragment.
 *
 * Composing "Checked " with a relative time is fine right up until there is no
 * time to be relative to, at which point a freshly tracked product reads
 * "Checked never checked".
 */
function lastCheckedLabel(product: TrackedProductOut): string {
  if (!product.last_checked_at) return 'Not checked yet';

  const when = relativeTime(product.last_checked_at);
  return product.last_check_status && product.last_check_status !== 'ok'
    ? `Check ${product.last_check_status} · ${when}`
    : `Checked ${when}`;
}

interface Props {
  product: TrackedProductOut;
  onOpen: (product: TrackedProductOut) => void;
  onPauseToggle: (product: TrackedProductOut) => void;
  onDelete: (product: TrackedProductOut) => void;
  onCheck: (product: TrackedProductOut) => void;
  busy?: boolean;
}

export function ProductCard({ product, onOpen, onPauseToggle, onDelete, onCheck, busy }: Props) {
  const [imageFailed, setImageFailed] = useState(false);

  const price = product.current_price ? Number.parseFloat(product.current_price) : undefined;
  const original = product.original_price ? Number.parseFloat(product.original_price) : undefined;
  const lowest = product.lowest_price ? Number.parseFloat(product.lowest_price) : undefined;
  const atLowest = price !== undefined && lowest !== undefined && price <= lowest;

  const watched = product.variants.filter((variant) => variant.is_watched);

  return (
    <article className="group relative sw-fade">
      <button
        type="button"
        onClick={() => onOpen(product)}
        className="block w-full text-left"
        aria-label={`Open ${product.name}`}
      >
        <div className="relative w-full overflow-hidden" style={{ aspectRatio: '3 / 4', background: 'var(--sw-surface)' }}>
          {product.image_url && !imageFailed ? (
            <img
              src={product.image_url}
              alt={product.name}
              loading="lazy"
              className="h-full w-full object-cover transition-opacity duration-300 group-hover:opacity-90"
              onError={() => setImageFailed(true)}
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <span className="sw-label">No image</span>
            </div>
          )}

          {!product.tracking_enabled ? (
            <span
              className="sw-label absolute left-0 top-0 px-2 py-1"
              style={{ background: 'var(--sw-bg)', color: 'var(--sw-fg)' }}
            >
              Paused
            </span>
          ) : atLowest ? (
            <span
              className="sw-label absolute left-0 top-0 px-2 py-1"
              style={{ background: 'var(--sw-sale)', color: '#fff' }}
            >
              Lowest
            </span>
          ) : null}
        </div>

        <div className="pt-3">
          <div className="sw-label truncate">{product.store ?? 'Unknown store'}</div>
          <h3 className="mt-1 truncate text-[13px] font-normal leading-snug">{product.name}</h3>

          <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className={`text-[13px] ${product.discount_percentage ? 'sw-price-sale' : ''}`}>
              {formatPrice(price, product.currency ?? undefined)}
            </span>
            {original !== undefined && price !== undefined && original > price ? (
              <span className="sw-price-was">{formatPrice(original, product.currency ?? undefined)}</span>
            ) : null}
            {product.discount_percentage ? (
              <span className="sw-label" style={{ color: 'var(--sw-sale)' }}>
                −{product.discount_percentage}%
              </span>
            ) : null}
          </div>

          <div className="mt-2 flex items-center gap-3">
            <StockLabel status={product.availability} />
            {watched.length ? (
              <span className="sw-label truncate">
                {watched.map((variant) => variant.variant_name).join(' · ')}
              </span>
            ) : null}
          </div>

          <div className="sw-label mt-1.5">{lastCheckedLabel(product)}</div>
        </div>
      </button>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 opacity-0 transition-opacity duration-200 focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
        <a
          href={product.url}
          target="_blank"
          rel="noopener noreferrer"
          className="sw-label underline underline-offset-4"
        >
          Open
        </a>
        <button
          type="button"
          onClick={() => onCheck(product)}
          disabled={busy}
          className="sw-label underline underline-offset-4 disabled:no-underline disabled:opacity-50"
        >
          {busy ? 'Checking' : 'Check now'}
        </button>
        <button type="button" onClick={() => onPauseToggle(product)} className="sw-label underline underline-offset-4">
          {product.tracking_enabled ? 'Pause' : 'Resume'}
        </button>
        <button
          type="button"
          onClick={() => onDelete(product)}
          className="sw-label underline underline-offset-4"
          style={{ color: 'var(--sw-sale)' }}
        >
          Delete
        </button>
      </div>
    </article>
  );
}
