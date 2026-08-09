/**
 * The one place message shapes are defined.
 *
 * Three contexts talk to each other — popup, injected content script, and the
 * service worker — so the payloads are typed here rather than being stringly
 * duplicated in three files.
 */

import type { DetectionResult } from './types';

export const MESSAGE = {
  /** popup -> content script: "tell me what product is on this page" */
  DETECT: 'stockwatch:detect',
  /** content script -> service worker: cache the last result for this tab */
  RESULT: 'stockwatch:result',
  /** popup -> service worker: read that cache back */
  GET_CACHED: 'stockwatch:get-cached',
  /** liveness probe used to decide whether injection is needed */
  PING: 'stockwatch:ping',
} as const;

export interface DetectRequest {
  type: typeof MESSAGE.DETECT;
  /** Globals harvested from the page's MAIN world by the popup. */
  pageGlobals: Record<string, unknown>;
}

export interface PingRequest {
  type: typeof MESSAGE.PING;
}

export interface ResultMessage {
  type: typeof MESSAGE.RESULT;
  result: DetectionResult;
}

export interface GetCachedRequest {
  type: typeof MESSAGE.GET_CACHED;
  tabId: number;
}

export type ExtensionMessage =
  | DetectRequest
  | PingRequest
  | ResultMessage
  | GetCachedRequest;

/**
 * `chrome.tabs.sendMessage` hangs forever if the receiving frame goes away
 * mid-flight (navigation, bfcache eviction). Every call is raced against a
 * timeout so the popup can show a real error instead of a permanent spinner.
 */
export function sendToTab<T>(tabId: number, message: ExtensionMessage, timeoutMs = 8000): Promise<T> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error('The page did not respond in time.'));
    }, timeoutMs);

    chrome.tabs.sendMessage(tabId, message, (response: T) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message ?? 'Could not reach the page.'));
        return;
      }
      resolve(response);
    });
  });
}
