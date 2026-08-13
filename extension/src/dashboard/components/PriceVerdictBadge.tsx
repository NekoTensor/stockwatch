/**
 * The one-word answer.
 *
 * A chart tells you what happened; this tells you what to do. It is the only
 * place in the interface that gives an opinion, so it earns its colour — and it
 * says nothing at all when the history is too short to have one.
 */

import type { PriceVerdict } from '../../lib/api';

const COPY: Record<PriceVerdict, { label: string; colour: string } | null> = {
  buy: { label: 'Good time to buy', colour: 'var(--sw-stock)' },
  fair: { label: 'Fair price', colour: 'var(--sw-muted)' },
  high: { label: 'Price is high', colour: 'var(--sw-sale)' },
  // Deliberately renders nothing: a shrug is not worth a badge.
  unknown: null,
};

export function PriceVerdictBadge({
  verdict,
  reason,
  compact = false,
}: {
  verdict: PriceVerdict;
  reason?: string;
  compact?: boolean;
}) {
  const copy = COPY[verdict];
  if (!copy) return null;

  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={reason || undefined}
      style={{ color: copy.colour }}
    >
      <span className="inline-block h-[5px] w-[5px] shrink-0" style={{ background: copy.colour }} aria-hidden="true" />
      <span className="sw-label" style={{ color: copy.colour }}>
        {copy.label}
      </span>
      {!compact && reason ? (
        <span className="sw-label" style={{ color: 'var(--sw-faint)' }}>
          · {reason}
        </span>
      ) : null}
    </span>
  );
}
