/**
 * Harvests the page's own JavaScript state.
 *
 * Content scripts run in an isolated world: they can read the DOM but *not*
 * `window.__NEXT_DATA__`, because that lives on the page's own `window`. This
 * function is therefore injected into the MAIN world by the popup via
 * `chrome.scripting.executeScript({ world: 'MAIN', func })`.
 *
 * IMPORTANT: it is serialised with `Function.prototype.toString()` before it is
 * injected, so it must be completely self-contained — no imports, no closure
 * variables, no helpers from this module. Everything it needs is declared
 * inside the function body.
 */
export function readPageGlobals(): Record<string, unknown> {
  const KNOWN_KEYS = [
    '__NEXT_DATA__',
    '__NUXT__',
    '__INITIAL_STATE__',
    '__PRELOADED_STATE__',
    '__APOLLO_STATE__',
    '__REDUX_STATE__',
    '__INITIAL_DATA__',
    '__remixContext',
    '__staticRouterHydrationData',
    'dataLayer',
    'digitalData',
    'utag_data',
    'productData',
    'pdpData',
    'product',
    '__myx',
    '__PRODUCT__',
    '_sharedData',
    'ShopifyAnalytics',
    'meta',
  ];

  const TOTAL_BUDGET = 2_500_000; // characters of JSON across everything
  const PER_VALUE_LIMIT = 1_500_000;
  const MAX_DEPTH = 12;

  let spent = 0;

  /** Depth-capped, cycle-safe snapshot. Functions and DOM nodes are dropped. */
  function snapshot(value: unknown, depth: number, seen: Set<object>): unknown {
    if (depth > MAX_DEPTH) return undefined;
    if (value === null) return null;

    const kind = typeof value;
    if (kind === 'string') return (value as string).length > 5000 ? (value as string).slice(0, 5000) : value;
    if (kind === 'number' || kind === 'boolean') return value;
    if (kind !== 'object') return undefined;

    const obj = value as object;
    if (seen.has(obj)) return undefined;

    // DOM nodes, windows and typed arrays are never product data.
    if (typeof Node !== 'undefined' && obj instanceof Node) return undefined;
    if (typeof Window !== 'undefined' && obj instanceof Window) return undefined;
    if (ArrayBuffer.isView(obj)) return undefined;

    seen.add(obj);
    try {
      if (Array.isArray(obj)) {
        const out: unknown[] = [];
        for (let i = 0; i < obj.length && i < 500; i += 1) {
          const item = snapshot(obj[i], depth + 1, seen);
          if (item !== undefined) out.push(item);
        }
        return out;
      }

      const out: Record<string, unknown> = {};
      let keys: string[] = [];
      try {
        keys = Object.keys(obj);
      } catch {
        return undefined;
      }

      for (const key of keys.slice(0, 300)) {
        let child: unknown;
        try {
          child = (obj as Record<string, unknown>)[key]; // getters can throw
        } catch {
          continue;
        }
        const snapped = snapshot(child, depth + 1, seen);
        if (snapped !== undefined) out[key] = snapped;
      }
      return out;
    } finally {
      seen.delete(obj);
    }
  }

  function take(value: unknown): unknown {
    if (value === null || value === undefined) return undefined;
    if (typeof value !== 'object') return undefined;
    if (spent >= TOTAL_BUDGET) return undefined;

    const snapped = snapshot(value, 0, new Set<object>());
    if (snapped === undefined) return undefined;

    let json: string;
    try {
      json = JSON.stringify(snapped);
    } catch {
      return undefined;
    }
    if (!json || json.length > PER_VALUE_LIMIT || spent + json.length > TOTAL_BUDGET) return undefined;

    spent += json.length;
    return snapped;
  }

  const result: Record<string, unknown> = {};
  const scope = window as unknown as Record<string, unknown>;

  for (const key of KNOWN_KEYS) {
    try {
      const value = take(scope[key]);
      if (value !== undefined) result[key] = value;
    } catch {
      /* a global that throws on access is not our problem */
    }
  }

  // Beyond the known names, sweep for globals that *look* like app state.
  // This is what gives an unrecognised store a chance on day one.
  try {
    const pattern = /^(__|_?(initial|preloaded|app|page|product|pdp|catalog|shop)[_a-z]*)/i;
    let extra = 0;
    for (const key of Object.keys(scope)) {
      if (extra >= 12 || spent >= TOTAL_BUDGET) break;
      if (result[key] !== undefined || !pattern.test(key)) continue;
      const value = take(scope[key]);
      if (value !== undefined) {
        result[key] = value;
        extra += 1;
      }
    }
  } catch {
    /* enumeration blocked — the known keys above are enough */
  }

  return result;
}
