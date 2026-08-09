/**
 * Tracking options and the call to action.
 *
 * Talks to the API. When the user is not signed in it says so and hands off to
 * the sign-in screen rather than silently saving nothing; when the backend is
 * unreachable it keeps the selection locally so a dropped connection does not
 * lose the user's work.
 */

import { useMemo, useState } from 'react';

import { ApiError, api } from '../../lib/api';
import { currencySymbol, formatPrice } from '../../lib/price';
import { saveDraft } from '../../lib/storage';
import type { ProductData } from '../../lib/types';
import { CheckIcon, Checkbox, Spinner } from './ui';

type State = 'idle' | 'saving' | 'tracked' | 'saved-locally';

interface Props {
  product: ProductData;
  selectedVariantIds: string[];
  signedIn: boolean;
  alreadyTracked: boolean;
  onNeedsAuth: () => void;
  onTracked: () => void;
}

export function TrackingPanel({
  product,
  selectedVariantIds,
  signedIn,
  alreadyTracked,
  onNeedsAuth,
  onTracked,
}: Props) {
  const hasPrice = product.currentPrice !== undefined;
  const hasVariants = product.variants.length > 0;

  const [trackStock, setTrackStock] = useState(hasVariants || product.availability !== 'unknown');
  const [trackPrice, setTrackPrice] = useState(hasPrice);
  const [targetPrice, setTargetPrice] = useState('');
  const [state, setState] = useState<State>(alreadyTracked ? 'tracked' : 'idle');
  const [error, setError] = useState<string | null>(null);

  const suggested = useMemo(() => {
    if (product.currentPrice === undefined) return undefined;
    return Math.max(1, Math.round((product.currentPrice * 0.85) / 10) * 10);
  }, [product.currentPrice]);

  const parsedTarget = targetPrice ? Number.parseFloat(targetPrice.replace(/[^\d.]/g, '')) : undefined;
  const targetIsUseless =
    parsedTarget !== undefined &&
    Number.isFinite(parsedTarget) &&
    product.currentPrice !== undefined &&
    parsedTarget >= product.currentPrice;

  const nothingSelected = !trackStock && !trackPrice;

  const track = async () => {
    if (!signedIn) {
      onNeedsAuth();
      return;
    }

    setState('saving');
    setError(null);

    const options = {
      variantIds: selectedVariantIds,
      trackStock,
      trackPrice,
      targetPrice: parsedTarget !== undefined && Number.isFinite(parsedTarget) ? parsedTarget : undefined,
    };

    try {
      await api.track(product, options);
      setState('tracked');
      onTracked();
    } catch (caught) {
      const apiError = caught as ApiError;

      if (apiError.isAuthError) {
        setState('idle');
        onNeedsAuth();
        return;
      }

      // Unreachable backend: keep the selection rather than losing it, and be
      // honest that nothing is being monitored yet.
      await saveDraft(product, options);
      setState('saved-locally');
      setError(apiError.message);
    }
  };

  if (state === 'tracked') {
    return (
      <div className="sw-rule px-5 py-5">
        <div className="flex items-start gap-3">
          <span className="sw-check sw-check-on mt-0.5">
            <CheckIcon />
          </span>
          <div className="min-w-0">
            <p className="text-[12px] leading-tight">Tracking</p>
            <p className="mt-1 text-[11px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
              {selectedVariantIds.length
                ? `Watching ${selectedVariantIds.length} ${selectedVariantIds.length > 1 ? 'options' : 'option'}. `
                : ''}
              We check the page on a schedule and alert you when something changes.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setState('idle')}
          className="sw-label mt-4 underline underline-offset-4"
        >
          Edit
        </button>
      </div>
    );
  }

  return (
    <div className="sw-rule px-5 py-4">
      <h2 className="sw-label mb-2">Alert me about</h2>

      <Checkbox
        checked={trackStock}
        onChange={setTrackStock}
        label="Stock availability"
        hint={hasVariants ? 'For the options selected above' : 'For the whole product'}
      />
      <Checkbox
        checked={trackPrice}
        onChange={setTrackPrice}
        label="Price changes"
        hint={hasPrice ? `Currently ${formatPrice(product.currentPrice, product.currency)}` : 'No price detected'}
      />

      {trackPrice && hasPrice ? (
        <div className="sw-fade mt-3">
          <label htmlFor="target-price" className="sw-label mb-1 block">
            Target price
          </label>
          <div className="flex items-baseline gap-1">
            <span className="text-[13px]" style={{ color: 'var(--sw-faint)' }}>
              {currencySymbol(product.currency).trim()}
            </span>
            <input
              id="target-price"
              inputMode="decimal"
              value={targetPrice}
              onChange={(event) => setTargetPrice(event.target.value)}
              placeholder={suggested ? String(suggested) : 'Optional'}
              className="sw-input"
            />
          </div>
          {targetIsUseless ? (
            <p className="mt-1.5 text-[10px]" style={{ color: 'var(--sw-sale)' }}>
              At or above the current price — you would be alerted immediately.
            </p>
          ) : null}
        </div>
      ) : null}

      {state === 'saved-locally' ? (
        <p className="mt-3 text-[10px] leading-relaxed" style={{ color: 'var(--sw-sale)' }}>
          Saved on this device only — {error} Nothing is being monitored until the backend is reachable.
        </p>
      ) : null}

      <button type="button" disabled={nothingSelected || state === 'saving'} onClick={track} className="sw-button mt-5">
        {state === 'saving' ? <Spinner className="mr-2 h-3 w-3" /> : null}
        {nothingSelected ? 'Choose what to track' : signedIn ? 'Track product' : 'Sign in to track'}
      </button>
    </div>
  );
}
