/**
 * "Show your working".
 *
 * Collapsed by default. Every field carries the layer that produced it, which
 * when a store changes its markup is the difference between "detection broke"
 * and "the JSON-LD price went stale and we correctly fell through to the DOM".
 */

import { useState } from 'react';

import type { DetectionResult, SourceLayer } from '../../lib/types';
import { PlusIcon } from './ui';

const LAYER_LABEL: Record<SourceLayer, string> = {
  jsonld: 'JSON-LD',
  microdata: 'Microdata',
  embedded: 'Embedded JSON',
  opengraph: 'OpenGraph',
  meta: 'Meta tags',
  adapter: 'Store adapter',
  dom: 'DOM',
  url: 'URL',
};

const FIELD_LABEL: Record<string, string> = {
  productName: 'Name',
  brand: 'Brand',
  currentPrice: 'Price',
  originalPrice: 'Was',
  currency: 'Currency',
  imageUrl: 'Image',
  images: 'Gallery',
  sku: 'SKU',
  productId: 'Product ID',
  category: 'Category',
  availability: 'Availability',
  variants: 'Variants',
  canonicalUrl: 'Canonical',
  description: 'Description',
};

export function DetectionDetails({ result }: { result: DetectionResult }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const entries = Object.entries(result.provenance).filter(([, layer]) => Boolean(layer));

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="sw-rule">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-5 py-3.5"
      >
        <span className="sw-label">Detection · {result.confidence}% confidence</span>
        <PlusIcon open={open} />
      </button>

      {open ? (
        <div className="sw-fade space-y-4 px-5 pb-5">
          <dl className="space-y-1.5 text-[11px]">
            <Row label="Adapter" value={result.adapterId} />
            <Row
              label="Layers"
              value={result.layersUsed.length ? result.layersUsed.map((l) => LAYER_LABEL[l]).join(', ') : 'none'}
            />
            <Row label="Time" value={`${result.durationMs} ms`} />
          </dl>

          {entries.length ? (
            <div>
              <div className="sw-label mb-1.5">Field sources</div>
              <dl className="space-y-1 text-[11px]">
                {entries.map(([field, layer]) => (
                  <Row
                    key={field}
                    label={FIELD_LABEL[field] ?? field}
                    value={LAYER_LABEL[layer as SourceLayer]}
                  />
                ))}
              </dl>
            </div>
          ) : null}

          {result.missing.length ? (
            <p className="text-[11px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
              Not detected: {result.missing.join(', ').toLowerCase()}.
            </p>
          ) : null}

          {result.warnings.length ? (
            <ul className="space-y-1 text-[11px]" style={{ color: 'var(--sw-muted)' }}>
              {result.warnings.map((warning) => (
                <li key={warning}>— {warning}</li>
              ))}
            </ul>
          ) : null}

          <button type="button" onClick={copy} className="sw-button-ghost w-full">
            {copied ? 'Copied' : 'Copy JSON'}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt style={{ color: 'var(--sw-muted)' }}>{label}</dt>
      <dd className="truncate text-right">{value}</dd>
    </div>
  );
}
