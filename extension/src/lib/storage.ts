/**
 * Local persistence — the offline fallback for tracking.
 *
 * When the API cannot be reached, the user's selection is kept here as a draft
 * rather than being lost, and replayed to `POST /api/products/track` once the
 * backend is available again. That is why a draft carries the whole normalised
 * product rather than just a URL: it has to be sufficient on its own.
 */

import type { ProductData, TrackingDraft } from './types';

const DRAFTS_KEY = 'stockwatch:drafts';
const MAX_DRAFTS = 200;

function storage(): chrome.storage.LocalStorageArea | undefined {
  return typeof chrome !== 'undefined' ? chrome.storage?.local : undefined;
}

export async function listDrafts(): Promise<TrackingDraft[]> {
  const area = storage();
  if (!area) return [];
  const stored = await area.get(DRAFTS_KEY);
  const drafts = stored?.[DRAFTS_KEY];
  return Array.isArray(drafts) ? (drafts as TrackingDraft[]) : [];
}

/** Same product, same page — used to show the "Already tracking" state. */
export async function findDraft(productUrl: string): Promise<TrackingDraft | undefined> {
  const drafts = await listDrafts();
  return drafts.find((draft) => draft.product.productUrl === productUrl);
}

export async function saveDraft(
  product: ProductData,
  options: { variantIds: string[]; trackStock: boolean; trackPrice: boolean; targetPrice?: number },
): Promise<TrackingDraft> {
  const drafts = await listDrafts();
  const existing = drafts.find((draft) => draft.product.productUrl === product.productUrl);

  const draft: TrackingDraft = {
    id: existing?.id ?? `draft_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    product,
    variantIds: options.variantIds,
    trackStock: options.trackStock,
    trackPrice: options.trackPrice,
    targetPrice: options.targetPrice,
    createdAt: existing?.createdAt ?? new Date().toISOString(),
  };

  const next = [draft, ...drafts.filter((item) => item.id !== draft.id)].slice(0, MAX_DRAFTS);
  await storage()?.set({ [DRAFTS_KEY]: next });
  return draft;
}

export async function removeDraft(id: string): Promise<void> {
  const drafts = await listDrafts();
  await storage()?.set({ [DRAFTS_KEY]: drafts.filter((draft) => draft.id !== id) });
}
