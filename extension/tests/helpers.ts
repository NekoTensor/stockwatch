import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { JSDOM } from 'jsdom';

import type { DetectionContext } from '../src/lib/types';
import { normaliseHostname } from '../src/lib/url';

const here = path.dirname(fileURLToPath(import.meta.url));

/**
 * Build a detection context from a saved page.
 *
 * A real `JSDOM` instance (rather than `DOMParser`) is used so the document has
 * a `defaultView` and therefore working `getComputedStyle` — the DOM layer
 * reads computed styles to spot struck-through prices and greyed-out sizes.
 */
export function contextFromFixture(
  fixture: string,
  url: string,
  pageGlobals: Record<string, unknown> = {},
): DetectionContext {
  const html = readFileSync(path.join(here, 'fixtures', fixture), 'utf8');
  const dom = new JSDOM(html, { url });
  return {
    doc: dom.window.document,
    url,
    hostname: normaliseHostname(url),
    pageGlobals,
  };
}

/** Build a context from an inline HTML string, for one-off cases. */
export function contextFromHtml(
  html: string,
  url: string,
  pageGlobals: Record<string, unknown> = {},
): DetectionContext {
  const dom = new JSDOM(html, { url });
  return { doc: dom.window.document, url, hostname: normaliseHostname(url), pageGlobals };
}
