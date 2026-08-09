/**
 * The detail view: one product, its price history, its variants and its
 * settings. Slides in over the grid rather than navigating away, so the
 * position in a long list is never lost.
 */

import { useEffect, useState } from 'react';

import { api, type ProductDetail, type TrackedProductOut } from '../../lib/api';
import { currencySymbol, formatPrice } from '../../lib/price';
import { StockLabel } from '../../popup/components/ui';
import { PriceChart, type PricePoint } from './PriceChart';

type Range = '7d' | '30d' | '90d' | 'all';

const RANGES: Range[] = ['7d', '30d', '90d', 'all'];
const RANGE_LABEL: Record<Range, string> = { '7d': '7 days', '30d': '30 days', '90d': '90 days', all: 'All' };

export function ProductPanel({
  product,
  onClose,
  onChanged,
}: {
  product: TrackedProductOut;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [points, setPoints] = useState<PricePoint[]>([]);
  const [range, setRange] = useState<Range>('30d');
  const [target, setTarget] = useState(product.target_price ?? '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [loaded, history] = await Promise.all([
        api.getProduct(product.id).catch(() => null),
        api.priceHistory(product.id, range).catch(() => null),
      ]);
      if (cancelled) return;
      if (loaded) setDetail(loaded);
      if (history) setPoints(history.points);
    })();
    return () => {
      cancelled = true;
    };
  }, [product.id, range]);

  // Escape closes the panel: it is a modal layer, and a modal that traps you is
  // worse than no modal.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const stats = detail?.price_stats;
  const current = detail ?? product;

  const toggleVariant = async (variantId: string, watched: boolean) => {
    const next = new Set(current.variants.filter((v) => v.is_watched).map((v) => v.variant_id));
    if (watched) next.add(variantId);
    else next.delete(variantId);

    await api.updateProduct(product.id, { watched_variant_ids: [...next] });
    const reloaded = await api.getProduct(product.id);
    setDetail(reloaded);
    onChanged();
  };

  const saveTarget = async () => {
    setSaving(true);
    try {
      const parsed = Number.parseFloat(String(target).replace(/[^\d.]/g, ''));
      await api.updateProduct(product.id, {
        target_price: Number.isFinite(parsed) && parsed > 0 ? parsed : null,
      });
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label={product.name}>
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0"
        style={{ background: 'rgb(0 0 0 / 35%)' }}
      />

      <div
        className="sw-fade relative h-full w-full max-w-[560px] overflow-y-auto"
        style={{ background: 'var(--sw-bg)', borderLeft: '1px solid var(--sw-line)' }}
      >
        <div
          className="sticky top-0 z-10 flex items-center justify-between px-8 py-4"
          style={{ background: 'var(--sw-bg)', borderBottom: '1px solid var(--sw-line)' }}
        >
          <span className="sw-label truncate">{current.store}</span>
          <button type="button" onClick={onClose} className="sw-label underline underline-offset-4">
            Close
          </button>
        </div>

        <div className="px-8 py-6">
          <div className="flex gap-5">
            {current.image_url ? (
              <img
                src={current.image_url}
                alt={current.name}
                className="w-[132px] shrink-0 object-cover"
                style={{ aspectRatio: '3 / 4', background: 'var(--sw-surface)' }}
              />
            ) : null}

            <div className="min-w-0 flex-1">
              <h2 className="text-[15px] font-normal leading-snug">{current.name}</h2>
              {current.brand ? <p className="sw-label mt-1.5">{current.brand}</p> : null}

              <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className={`text-[16px] ${current.discount_percentage ? 'sw-price-sale' : ''}`}>
                  {formatPrice(
                    current.current_price ? Number.parseFloat(current.current_price) : undefined,
                    current.currency ?? undefined,
                  )}
                </span>
                {current.original_price ? (
                  <span className="sw-price-was">
                    {formatPrice(Number.parseFloat(current.original_price), current.currency ?? undefined)}
                  </span>
                ) : null}
                {current.discount_percentage ? (
                  <span className="sw-label" style={{ color: 'var(--sw-sale)' }}>
                    −{current.discount_percentage}%
                  </span>
                ) : null}
              </div>

              <div className="mt-3">
                <StockLabel status={current.availability} />
              </div>

              <a
                href={current.url}
                target="_blank"
                rel="noopener noreferrer"
                className="sw-label mt-4 inline-block underline underline-offset-4"
              >
                Open product
              </a>
            </div>
          </div>
        </div>

        <section className="sw-rule px-8 py-6">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="sw-label">Price history</h3>
            <div className="flex gap-3">
              {RANGES.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setRange(option)}
                  className={`sw-nav ${range === option ? 'sw-nav-active' : ''}`}
                >
                  {RANGE_LABEL[option]}
                </button>
              ))}
            </div>
          </div>

          <PriceChart points={points} currency={current.currency} />

          {stats ? (
            <dl className="mt-6 grid grid-cols-2 gap-x-8 gap-y-2 text-[12px] sm:grid-cols-4">
              <Stat label="Lowest" value={formatPrice(num(stats.lowest), current.currency ?? undefined)} />
              <Stat label="Highest" value={formatPrice(num(stats.highest), current.currency ?? undefined)} />
              <Stat label="Average" value={formatPrice(num(stats.average), current.currency ?? undefined)} />
              <Stat label="30-day low" value={formatPrice(num(stats.lowest_30d), current.currency ?? undefined)} />
            </dl>
          ) : null}
        </section>

        {current.variants.length ? (
          <section className="sw-rule px-8 py-6">
            <h3 className="sw-label mb-3">Options — tap to watch</h3>
            <div className="grid grid-cols-5 gap-px">
              {current.variants.map((variant) => {
                const soldOut = variant.current_stock === 'out_of_stock';
                const classes = [
                  'sw-chip',
                  variant.is_watched ? 'sw-chip-selected' : '',
                  soldOut ? 'sw-chip-out' : '',
                ]
                  .filter(Boolean)
                  .join(' ');
                return (
                  <button
                    key={variant.id}
                    type="button"
                    onClick={() => void toggleVariant(variant.variant_id, !variant.is_watched)}
                    className={classes}
                    title={`${variant.variant_name} — ${variant.current_stock.replace(/_/g, ' ')}`}
                  >
                    <span className="truncate px-1">{variant.variant_name}</span>
                  </button>
                );
              })}
            </div>
          </section>
        ) : null}

        <section className="sw-rule px-8 py-6">
          <h3 className="sw-label mb-3">Target price</h3>
          <div className="flex items-end gap-3">
            <span className="pb-2 text-[13px]" style={{ color: 'var(--sw-faint)' }}>
              {currencySymbol(current.currency ?? undefined).trim()}
            </span>
            <input
              value={target ?? ''}
              onChange={(event) => setTarget(event.target.value)}
              inputMode="decimal"
              placeholder="Optional"
              className="sw-input flex-1"
            />
            <button type="button" onClick={saveTarget} disabled={saving} className="sw-button-ghost">
              {saving ? 'Saving' : 'Save'}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function num(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="sw-label">{label}</dt>
      <dd className="mt-0.5">{value}</dd>
    </div>
  );
}
