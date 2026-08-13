/**
 * Watch rules: the standing questions a user has about a product.
 *
 * The form is deliberately two dropdowns and a number rather than a query
 * builder. Every rule people actually want — "my size, back in stock", "under
 * 8,000", "my size AND under 4,000" — is expressible in that much, and anything
 * more would be a language to learn rather than a setting to fill in.
 */

import { useEffect, useState } from 'react';

import {
  api,
  type PriceConditionKind,
  type StockCondition,
  type TrackedVariantOut,
  type WatchRuleInput,
  type WatchRuleOut,
} from '../../lib/api';
import { currencySymbol } from '../../lib/price';
import { Checkbox, Spinner } from '../../popup/components/ui';

const STOCK_OPTIONS: Array<{ value: StockCondition; label: string }> = [
  { value: 'any', label: 'Ignore stock' },
  { value: 'back_in_stock', label: 'Comes back in stock' },
  { value: 'in_stock', label: 'Is in stock' },
  { value: 'out_of_stock', label: 'Sells out' },
];

const PRICE_OPTIONS: Array<{ value: PriceConditionKind; label: string }> = [
  { value: 'any', label: 'Ignore price' },
  { value: 'below', label: 'Is at or below' },
  { value: 'drops_by_percent', label: 'Drops by at least' },
  { value: 'at_lowest', label: 'Hits its lowest ever' },
  { value: 'below_average', label: 'Is below the 30-day average by' },
];

const NEEDS_PRICE: PriceConditionKind[] = ['below'];
const NEEDS_PERCENT: PriceConditionKind[] = ['drops_by_percent', 'below_average'];

interface Props {
  productId: number;
  variants: TrackedVariantOut[];
  currency: string | null;
  onChanged?: () => void;
}

export function WatchRules({ productId, variants, currency, onChanged }: Props) {
  const [rules, setRules] = useState<WatchRuleOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);

  const [draft, setDraft] = useState<WatchRuleInput>({
    variant_id: null,
    stock_condition: 'back_in_stock',
    price_condition: 'any',
    combine: 'all',
    notify_browser: true,
    notify_email: true,
    notify_discord: false,
  });

  const load = async () => {
    try {
      setRules(await api.listRules(productId));
    } catch (caught) {
      setError((caught as Error).message);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productId]);

  const create = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.createRule(productId, draft);
      setAdding(false);
      await load();
      onChanged?.();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (rule: WatchRuleOut) => {
    await api.updateRule(productId, rule.id, { is_active: !rule.is_active });
    await load();
  };

  const remove = async (rule: WatchRuleOut) => {
    await api.deleteRule(productId, rule.id);
    await load();
    onChanged?.();
  };

  const symbol = currencySymbol(currency ?? undefined).trim();

  return (
    <section className="sw-rule px-8 py-6">
      <div className="mb-4 flex items-baseline justify-between">
        <h3 className="sw-label">Alert rules</h3>
        <button
          type="button"
          onClick={() => setAdding((value) => !value)}
          className="sw-label underline underline-offset-4"
        >
          {adding ? 'Cancel' : 'Add rule'}
        </button>
      </div>

      {rules === null ? (
        <div className="sw-skeleton h-12 w-full" />
      ) : rules.length === 0 && !adding ? (
        <p className="text-[12px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
          No rules yet. Without one, this product uses its own alert settings — stock and price
          changes on whatever you are watching. Add a rule to be more specific.
        </p>
      ) : (
        <ul style={{ borderTop: rules.length ? '1px solid var(--sw-line)' : undefined }}>
          {rules.map((rule) => (
            <li
              key={rule.id}
              className="flex items-start justify-between gap-4 py-3"
              style={{ borderBottom: '1px solid var(--sw-line)' }}
            >
              <div className="min-w-0">
                <p className="text-[13px] leading-snug" style={{ opacity: rule.is_active ? 1 : 0.45 }}>
                  {rule.description}
                </p>
                <p className="sw-label mt-1">
                  {[
                    rule.notify_browser && 'Browser',
                    rule.notify_email && 'Email',
                    rule.notify_discord && 'Discord',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                  {rule.trigger_count > 0 ? ` · fired ${rule.trigger_count}×` : ''}
                  {rule.is_active ? '' : ' · paused'}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-4">
                <button type="button" onClick={() => toggleActive(rule)} className="sw-label underline underline-offset-4">
                  {rule.is_active ? 'Pause' : 'Resume'}
                </button>
                <button
                  type="button"
                  onClick={() => remove(rule)}
                  className="sw-label underline underline-offset-4"
                  style={{ color: 'var(--sw-sale)' }}
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <div className="sw-fade mt-5 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="sw-label mb-1 block">Which option</span>
              <select
                value={draft.variant_id ?? ''}
                onChange={(event) => setDraft({ ...draft, variant_id: event.target.value || null })}
                className="sw-input"
              >
                <option value="">Any option</option>
                {variants.map((variant) => (
                  <option key={variant.id} value={variant.variant_id}>
                    {variant.variant_name}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="sw-label mb-1 block">Stock</span>
              <select
                value={draft.stock_condition}
                onChange={(event) =>
                  setDraft({ ...draft, stock_condition: event.target.value as StockCondition })
                }
                className="sw-input"
              >
                {STOCK_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="sw-label mb-1 block">Price</span>
              <select
                value={draft.price_condition}
                onChange={(event) =>
                  setDraft({ ...draft, price_condition: event.target.value as PriceConditionKind })
                }
                className="sw-input"
              >
                {PRICE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            {NEEDS_PRICE.includes(draft.price_condition ?? 'any') ? (
              <label className="block">
                <span className="sw-label mb-1 block">Amount</span>
                <div className="flex items-baseline gap-1">
                  <span className="text-[13px]" style={{ color: 'var(--sw-faint)' }}>
                    {symbol}
                  </span>
                  <input
                    inputMode="decimal"
                    value={draft.price_value ?? ''}
                    onChange={(event) =>
                      setDraft({ ...draft, price_value: Number.parseFloat(event.target.value) || null })
                    }
                    className="sw-input"
                  />
                </div>
              </label>
            ) : null}

            {NEEDS_PERCENT.includes(draft.price_condition ?? 'any') ? (
              <label className="block">
                <span className="sw-label mb-1 block">Percent</span>
                <input
                  inputMode="decimal"
                  value={draft.percent_value ?? ''}
                  onChange={(event) =>
                    setDraft({ ...draft, percent_value: Number.parseFloat(event.target.value) || null })
                  }
                  className="sw-input"
                  placeholder="10"
                />
              </label>
            ) : null}
          </div>

          {draft.stock_condition !== 'any' && draft.price_condition !== 'any' ? (
            <label className="block max-w-[280px]">
              <span className="sw-label mb-1 block">Require</span>
              <select
                value={draft.combine}
                onChange={(event) => setDraft({ ...draft, combine: event.target.value as 'all' | 'any' })}
                className="sw-input"
              >
                <option value="all">Both conditions</option>
                <option value="any">Either condition</option>
              </select>
            </label>
          ) : null}

          <div>
            <span className="sw-label mb-1 block">Send to</span>
            <div className="flex flex-wrap gap-x-8">
              <Checkbox
                checked={draft.notify_browser ?? true}
                onChange={(value) => setDraft({ ...draft, notify_browser: value })}
                label="Browser"
              />
              <Checkbox
                checked={draft.notify_email ?? true}
                onChange={(value) => setDraft({ ...draft, notify_email: value })}
                label="Email"
              />
              <Checkbox
                checked={draft.notify_discord ?? false}
                onChange={(value) => setDraft({ ...draft, notify_discord: value })}
                label="Discord"
              />
            </div>
          </div>

          <button type="button" onClick={create} disabled={saving} className="sw-button max-w-[220px]">
            {saving ? <Spinner className="mr-2 h-3 w-3" /> : null}
            Create rule
          </button>
        </div>
      ) : null}

      {error ? (
        <p className="mt-3 text-[11px]" style={{ color: 'var(--sw-sale)' }}>
          {error}
        </p>
      ) : null}
    </section>
  );
}
