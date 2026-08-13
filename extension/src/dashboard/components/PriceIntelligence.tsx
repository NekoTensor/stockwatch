/**
 * The numbers under the chart.
 *
 * Ordered by how directly each one answers "should I buy": the verdict first,
 * then what you save against the recent norm, then the context that supports
 * it. Percentile is phrased as "cheaper than N% of checks" rather than as a
 * percentile, because nobody reads "18th percentile" as good news at a glance.
 */

import type { PriceStats } from '../../lib/api';
import { formatPrice } from '../../lib/price';
import { PriceVerdictBadge } from './PriceVerdictBadge';

function num(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function PriceIntelligence({
  stats,
  currency,
}: {
  stats: PriceStats;
  currency: string | null;
}) {
  const saving = num(stats.saving_vs_average);
  const average = num(stats.average_30d);
  const currencyCode = currency ?? undefined;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <PriceVerdictBadge verdict={stats.verdict} reason={stats.verdict_reason} />
      </div>

      <dl className="grid grid-cols-2 gap-x-8 gap-y-3 text-[12px] sm:grid-cols-4">
        <Stat label="Current" value={formatPrice(num(stats.current), currencyCode)} />
        <Stat label="30-day average" value={formatPrice(average, currencyCode)} />
        <Stat
          label="You save"
          value={saving ? formatPrice(saving, currencyCode) : '—'}
          tone={saving ? 'good' : undefined}
        />
        <Stat
          label="Cheaper than"
          value={stats.percentile === null ? '—' : `${100 - stats.percentile}% of checks`}
        />
      </dl>

      <dl className="mt-4 grid grid-cols-2 gap-x-8 gap-y-3 text-[12px] sm:grid-cols-4">
        <Stat label="All-time low" value={formatPrice(num(stats.lowest), currencyCode)} />
        <Stat label="All-time high" value={formatPrice(num(stats.highest), currencyCode)} />
        <Stat label="30-day median" value={formatPrice(num(stats.median_30d), currencyCode)} />
        <Stat
          label="Volatility"
          value={stats.volatility === null ? '—' : `${stats.volatility.toFixed(1)}%`}
        />
      </dl>

      <p className="sw-label mt-4">
        {stats.observations} price {stats.observations === 1 ? 'check' : 'checks'} recorded
      </p>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'good' }) {
  return (
    <div>
      <dt className="sw-label">{label}</dt>
      <dd className="mt-0.5" style={tone === 'good' ? { color: 'var(--sw-stock)' } : undefined}>
        {value}
      </dd>
    </div>
  );
}
