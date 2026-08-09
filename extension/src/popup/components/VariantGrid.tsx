/**
 * Variant picker.
 *
 * Sold-out options stay visible and struck through rather than being removed —
 * a shopper needs to know the size exists before they can ask to be told when
 * it returns. They are also selectable, which is the entire point of a restock
 * tracker, so a chip has to be able to say "sold out" and "selected" at once.
 */

import type { Variant, VariantType } from '../../lib/types';

const TYPE_LABEL: Record<VariantType, string> = {
  size: 'Size',
  color: 'Colour',
  shade: 'Shade',
  capacity: 'Capacity',
  length: 'Length',
  flavor: 'Flavour',
  style: 'Style',
  generic: 'Options',
};

export function variantGroupLabel(variants: Variant[]): string {
  const counts = new Map<VariantType, number>();
  for (const variant of variants) counts.set(variant.type, (counts.get(variant.type) ?? 0) + 1);
  const dominant = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'generic';
  return TYPE_LABEL[dominant];
}

export function VariantGrid({
  variants,
  selected,
  onToggle,
}: {
  variants: Variant[];
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="grid grid-cols-5 gap-px" style={{ background: 'transparent' }}>
      {variants.map((variant) => {
        const isSelected = selected.has(variant.id);
        const soldOut = variant.availability === 'out_of_stock';
        const unknown = variant.availability === 'unknown';

        const classes = [
          'sw-chip',
          isSelected ? 'sw-chip-selected' : '',
          soldOut ? 'sw-chip-out' : '',
        ]
          .filter(Boolean)
          .join(' ');

        const status = soldOut ? 'sold out' : unknown ? 'availability unknown' : 'in stock';

        return (
          <button
            key={variant.id}
            type="button"
            aria-pressed={isSelected}
            aria-label={`${variant.name} — ${status}`}
            title={`${variant.name} — ${status}`}
            onClick={() => onToggle(variant.id)}
            className={classes}
          >
            <span className="truncate px-1">{variant.name}</span>
            {unknown ? (
              <span className="ml-0.5 text-[9px] leading-none" style={{ color: 'var(--sw-faint)' }}>
                ?
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
