/**
 * Service worker.
 *
 * Two jobs, both small:
 *
 *   1. paint the toolbar badge for the tab the user is looking at;
 *   2. wake on an alarm, ask the backend whether anything happened, and raise a
 *      native notification for each thing that did.
 *
 * What it deliberately does *not* do is monitor products. An MV3 worker is
 * evicted after about thirty seconds of idle, so it cannot hold a schedule, and
 * a laptop is the wrong place to poll a thousand shops from. The backend does
 * that; this only delivers the result.
 */

import { ApiError, api, getSession } from '../lib/api';
import { MESSAGE, type ExtensionMessage } from '../lib/messaging';
import type { DetectionResult } from '../lib/types';

const POLL_ALARM = 'stockwatch:poll';
/** Chrome clamps alarms to a one-minute floor; five is polite and plenty. */
const POLL_MINUTES = 5;

/** tabId -> last result. Cleared when the tab navigates or closes. */
const cache = new Map<number, DetectionResult>();

function paintBadge(tabId: number, result: DetectionResult): void {
  const found = result.status === 'detected' || result.status === 'partial';
  void chrome.action.setBadgeText({ tabId, text: found ? '•' : '' });
  if (found) {
    void chrome.action.setBadgeBackgroundColor({ tabId, color: '#000000' });
    void chrome.action.setTitle({
      tabId,
      title: `StockWatch — ${result.product?.productName ?? 'product detected'}`,
    });
  }
}

chrome.runtime.onMessage.addListener((message: ExtensionMessage, sender, sendResponse) => {
  if (message?.type === MESSAGE.RESULT) {
    const tabId = sender.tab?.id;
    if (tabId !== undefined) {
      cache.set(tabId, message.result);
      paintBadge(tabId, message.result);
    }
    sendResponse({ ok: true });
    return false;
  }

  if (message?.type === MESSAGE.GET_CACHED) {
    sendResponse(cache.get(message.tabId) ?? null);
    return false;
  }

  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  cache.delete(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  // A new URL means the cached product no longer describes this tab.
  if (changeInfo.url || changeInfo.status === 'loading') {
    cache.delete(tabId);
    void chrome.action.setBadgeText({ tabId, text: '' });
  }
});

// ------------------------------------------------------- alert delivery ----

/** notificationId -> product URL, so a click can open the right page. */
const notificationTargets = new Map<string, string>();

async function deliverPendingAlerts(): Promise<void> {
  const session = await getSession();
  if (!session) return;

  let pending;
  try {
    pending = await api.undelivered();
  } catch (error) {
    // Offline, or the backend is down. Nothing is lost: the alerts stay
    // undelivered server-side and we will pick them up next time.
    if (!(error instanceof ApiError) || error.status !== 0) {
      console.warn('[StockWatch] could not fetch alerts:', error);
    }
    return;
  }

  if (!pending.items.length) return;

  const delivered: number[] = [];

  for (const item of pending.items) {
    const id = `stockwatch:${item.id}`;
    try {
      await chrome.notifications.create(id, {
        type: 'basic',
        iconUrl: chrome.runtime.getURL('icons/icon128.png'),
        title: item.title,
        message: item.message,
        contextMessage: item.product_name ?? undefined,
        priority: item.priority === 'high' ? 2 : 0,
        requireInteraction: item.priority === 'high',
      });
      if (item.product_url) notificationTargets.set(id, item.product_url);
      delivered.push(item.id);
    } catch (error) {
      console.warn('[StockWatch] could not raise notification:', error);
    }
  }

  // Only acknowledge what actually reached the user.
  if (delivered.length) {
    try {
      await api.markDelivered(delivered);
    } catch (error) {
      console.warn('[StockWatch] could not acknowledge alerts:', error);
    }
  }
}

chrome.notifications.onClicked.addListener((notificationId) => {
  const url = notificationTargets.get(notificationId);
  if (url) void chrome.tabs.create({ url });
  void chrome.notifications.clear(notificationId);
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === POLL_ALARM) void deliverPendingAlerts();
});

function ensureAlarm(): void {
  void chrome.alarms.get(POLL_ALARM).then((existing) => {
    if (!existing) {
      void chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES, delayInMinutes: 1 });
    }
  });
}

chrome.runtime.onInstalled.addListener((details) => {
  ensureAlarm();
  if (details.reason === 'install') {
    console.info('[StockWatch] installed — open any product page and click the toolbar icon.');
  }
});

// The worker is restarted constantly; re-arming on startup is what keeps the
// alarm alive across those restarts.
chrome.runtime.onStartup.addListener(ensureAlarm);
ensureAlarm();
