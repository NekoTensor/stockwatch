/**
 * The "click the icon and it already knows" flow, in one hook.
 *
 *   active tab -> MAIN-world globals -> inject content script -> detect
 *
 * Every step is failure-isolated: if the page's globals cannot be read we
 * still detect from the DOM and structured data, and the user sees a product
 * rather than an error.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { readPageGlobals } from '../../content/pageGlobals';
import { MESSAGE, sendToTab } from '../../lib/messaging';
import { findDraft } from '../../lib/storage';
import type { DetectionResult, TrackingDraft } from '../../lib/types';
import { isRestrictedPage } from '../../lib/url';

export type Phase = 'loading' | 'ready' | 'unsupported' | 'error';

export interface DetectionState {
  phase: Phase;
  result?: DetectionResult;
  tab?: chrome.tabs.Tab;
  existingDraft?: TrackingDraft;
  message?: string;
}

const CONTENT_SCRIPT = 'content.js';

async function activeTab(): Promise<chrome.tabs.Tab | undefined> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

/**
 * Read the page's own JavaScript state from the MAIN world. Failure here is
 * routine (CSP, a page that blocks injection) and never fatal.
 */
async function harvestGlobals(tabId: number): Promise<Record<string, unknown>> {
  try {
    const [injection] = await chrome.scripting.executeScript({
      target: { tabId },
      world: 'MAIN',
      func: readPageGlobals,
    });
    const value = injection?.result;
    return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

async function ensureContentScript(tabId: number): Promise<void> {
  try {
    await sendToTab(tabId, { type: MESSAGE.PING }, 400);
    return; // already listening from a previous open
  } catch {
    // Not injected yet — that is the normal path on the first click.
  }

  await chrome.scripting.executeScript({ target: { tabId }, files: [CONTENT_SCRIPT] });
}

export function useDetection(): DetectionState & { reload: () => void } {
  const [state, setState] = useState<DetectionState>({ phase: 'loading' });
  const runId = useRef(0);

  const run = useCallback(async () => {
    const id = (runId.current += 1);
    const commit = (next: DetectionState) => {
      if (runId.current === id) setState(next);
    };

    commit({ phase: 'loading' });

    const tab = await activeTab();
    if (!tab?.id || isRestrictedPage(tab.url)) {
      commit({
        phase: 'unsupported',
        tab,
        message: 'StockWatch can only read ordinary web pages. Open a product page and try again.',
      });
      return;
    }

    try {
      const [globals] = await Promise.all([harvestGlobals(tab.id), ensureContentScript(tab.id)]);

      const result = await sendToTab<DetectionResult>(tab.id, {
        type: MESSAGE.DETECT,
        pageGlobals: globals,
      });

      if (!result) {
        commit({ phase: 'error', tab, message: 'The page did not return a result. Try reloading it.' });
        return;
      }

      const existingDraft = result.product ? await findDraft(result.product.productUrl) : undefined;
      commit({ phase: 'ready', result, tab, existingDraft });
    } catch (error) {
      const reason = (error as Error).message ?? 'Unknown error';
      const blocked = /cannot access|extension manifest|chrome:\/\/|showing error page/i.test(reason);
      commit({
        phase: blocked ? 'unsupported' : 'error',
        tab,
        message: blocked
          ? 'This page does not allow extensions to read it.'
          : `${reason} Reload the page and try again.`,
      });
    }
  }, []);

  useEffect(() => {
    void run();
  }, [run]);

  return { ...state, reload: () => void run() };
}
