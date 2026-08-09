/**
 * Content script.
 *
 * Injected on demand when the user opens the popup — there is no declared
 * content script and no host permission, so StockWatch reads a page only at
 * the moment you ask it to, and only the tab you are looking at.
 *
 * It owns no detection logic of its own: it hands the live document to the
 * pipeline and returns the result.
 */

import { runDetection } from '../detection/pipeline';
import { MESSAGE, type ExtensionMessage } from '../lib/messaging';
import type { DetectionResult } from '../lib/types';
import { normaliseHostname } from '../lib/url';

declare global {
  interface Window {
    __stockwatchContentReady?: boolean;
  }
}

function detect(pageGlobals: Record<string, unknown>): DetectionResult {
  try {
    return runDetection({
      doc: document,
      url: location.href,
      hostname: normaliseHostname(location.href),
      pageGlobals: pageGlobals ?? {},
    });
  } catch (error) {
    return {
      status: 'error',
      confidence: 0,
      missing: [],
      warnings: [],
      provenance: {},
      layersUsed: [],
      adapterId: 'generic',
      durationMs: 0,
      error: (error as Error).message,
    };
  }
}

// The popup may inject this file again on a later open; the isolated world
// persists, so a flag keeps us from stacking duplicate listeners.
if (!window.__stockwatchContentReady) {
  window.__stockwatchContentReady = true;

  chrome.runtime.onMessage.addListener((message: ExtensionMessage, _sender, sendResponse) => {
    if (message?.type === MESSAGE.PING) {
      sendResponse({ ready: true });
      return false;
    }

    if (message?.type === MESSAGE.DETECT) {
      const result = detect(message.pageGlobals);
      sendResponse(result);

      // Fire-and-forget: lets the service worker badge the tab.
      try {
        chrome.runtime.sendMessage({ type: MESSAGE.RESULT, result }).catch(() => undefined);
      } catch {
        /* the worker may be asleep; the popup already has its answer */
      }
      return false;
    }

    return false;
  });
}
