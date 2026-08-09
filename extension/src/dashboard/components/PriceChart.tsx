/**
 * Price history, drawn as inline SVG.
 *
 * No chart library: the whole thing is one path, and pulling in a dependency
 * would cost more bytes than the feature. Visually it follows the same rules as
 * the rest of the interface — one hairline baseline, no gridlines, no legend,
 * labels in the small uppercase voice.
 */

import { useMemo, useState } from 'react';

import { formatPrice } from '../../lib/price';

export interface PricePoint {
  price: string;
  recorded_at: string;
}

interface Props {
  points: PricePoint[];
  currency: string | null;
  height?: number;
}

const PADDING = { top: 16, right: 8, bottom: 22, left: 8 };

export function PriceChart({ points, currency, height = 180 }: Props) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 720;

  const series = useMemo(
    () =>
      points
        .map((point) => ({ value: Number.parseFloat(point.price), at: new Date(point.recorded_at) }))
        .filter((point) => Number.isFinite(point.value)),
    [points],
  );

  if (series.length < 2) {
    return (
      <div className="flex items-center justify-center" style={{ height }}>
        <p className="sw-label">
          {series.length === 1 ? 'One observation so far' : 'No price history yet'}
        </p>
      </div>
    );
  }

  const values = series.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  // A flat series would otherwise divide by zero and collapse to the baseline.
  const span = max - min || max * 0.1 || 1;

  const innerWidth = width - PADDING.left - PADDING.right;
  const innerHeight = height - PADDING.top - PADDING.bottom;

  const x = (index: number) => PADDING.left + (index / (series.length - 1)) * innerWidth;
  const y = (value: number) => PADDING.top + innerHeight - ((value - min) / span) * innerHeight;

  // Step-after, not a smooth curve: a price holds until it changes, and
  // interpolating between observations would draw a change that never happened.
  const path = series
    .map((point, index) => {
      const px = x(index);
      const py = y(point.value);
      return index === 0 ? `M ${px} ${py}` : `H ${px} V ${py}`;
    })
    .join(' ');

  const areaPath = `${path} V ${PADDING.top + innerHeight} H ${x(0)} Z`;

  const lowestIndex = values.indexOf(min);
  const active = hover ?? series.length - 1;
  const activePoint = series[active];

  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between">
        <span className="sw-label">
          {activePoint.at.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}
        </span>
        <span className="text-[13px]">{formatPrice(activePoint.value, currency ?? undefined)}</span>
      </div>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        role="img"
        aria-label="Price history"
        onMouseLeave={() => setHover(null)}
      >
        <path d={areaPath} fill="currentColor" opacity="0.05" />
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.25" vectorEffect="non-scaling-stroke" />

        <line
          x1={PADDING.left}
          x2={width - PADDING.right}
          y1={PADDING.top + innerHeight}
          y2={PADDING.top + innerHeight}
          stroke="var(--sw-line)"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />

        {/* The lowest point is the one people are actually looking for. */}
        <circle cx={x(lowestIndex)} cy={y(min)} r="3" fill="var(--sw-sale)" />

        <circle cx={x(active)} cy={y(activePoint.value)} r="3" fill="currentColor" />

        {series.map((point, index) => (
          <rect
            key={`${point.at.toISOString()}-${index}`}
            x={x(index) - innerWidth / (series.length - 1) / 2}
            y={0}
            width={innerWidth / (series.length - 1)}
            height={height}
            fill="transparent"
            onMouseEnter={() => setHover(index)}
          />
        ))}
      </svg>

      <div className="mt-1 flex justify-between">
        <span className="sw-label">
          {series[0].at.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
        </span>
        <span className="sw-label" style={{ color: 'var(--sw-sale)' }}>
          Low {formatPrice(min, currency ?? undefined)}
        </span>
        <span className="sw-label">
          {series[series.length - 1].at.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
        </span>
      </div>
    </div>
  );
}
