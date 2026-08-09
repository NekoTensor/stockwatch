/**
 * Preview harness (development only — never bundled into `dist/`).
 *
 * Renders the real popup and the real dashboard in an ordinary browser tab by
 * stubbing the two things they cannot have outside an extension: the `chrome.*`
 * APIs and the backend.
 *
 * The popup runs the **real** detection pipeline against a saved fixture, so
 * what you see is what the extension would actually produce. The dashboard is
 * served canned API responses shaped exactly like the FastAPI schemas.
 *
 *   npm run preview
 *   /dev/preview.html?f=dom-only          popup, unknown-store fixture
 *   /dev/preview.html?view=dashboard      dashboard
 */

import { runDetection } from '../src/detection/pipeline';
import { MESSAGE } from '../src/lib/messaging';
import { normaliseHostname } from '../src/lib/url';

const params = new URLSearchParams(location.search);
const view = params.get('view') ?? 'popup';

/**
 * Force a colour scheme, for deterministic screenshots.
 *
 * The stylesheet keys off `prefers-color-scheme`, which a headless browser
 * inherits from the host OS. Re-declaring the palette here — rather than adding
 * a `data-theme` hook to the shipped CSS — keeps this entirely inside the dev
 * harness.
 */
function forceTheme(theme: 'light' | 'dark'): void {
  const palette =
    theme === 'dark'
      ? {
          '--sw-bg': '#0b0b0b', '--sw-fg': '#f2f2f2', '--sw-muted': '#9a9a9a',
          '--sw-faint': '#6b6b6b', '--sw-line': '#262626', '--sw-surface': '#151515',
          '--sw-sale': '#ff5a6e', '--sw-stock': '#4ade80',
        }
      : {
          '--sw-bg': '#ffffff', '--sw-fg': '#000000', '--sw-muted': '#767676',
          '--sw-faint': '#a3a3a3', '--sw-line': '#e5e5e5', '--sw-surface': '#f7f7f7',
          '--sw-sale': '#c8102e', '--sw-stock': '#1c7c3c',
        };

  // Set inline on <html> rather than as a <style> block: Vite injects the app's
  // CSS when the module loads, which is *after* this runs, so a stylesheet rule
  // of equal specificity would lose. An inline declaration always wins.
  const root = document.documentElement;
  for (const [key, value] of Object.entries(palette)) {
    root.style.setProperty(key, value);
  }
  root.style.colorScheme = theme;
  root.style.background = palette['--sw-bg'];
}

const theme = params.get('theme');
if (theme === 'light' || theme === 'dark') forceTheme(theme);

/**
 * Abstract stand-in for a product photograph.
 *
 * The fixtures point at invented domains, so nothing loads. Rather than
 * screenshotting a grid of "No image" boxes, the preview substitutes a soft
 * neutral panel — enough to show how the layout breathes without pretending to
 * be a real product shot.
 */
function placeholderImage(index: number): string {
  const palettes = [
    ['#efe9e3', '#cec5bb'],
    ['#e7e9ea', '#c4cace'],
    ['#f0eae9', '#d6c4c2'],
    ['#eceee9', '#c8cfc2'],
    ['#efece6', '#cfc3ae'],
  ];
  const [from, to] = palettes[index % palettes.length];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 400">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="${from}"/><stop offset="1" stop-color="${to}"/></linearGradient></defs>
<rect width="300" height="400" fill="url(#g)"/>
<circle cx="150" cy="158" r="66" fill="#ffffff" opacity="0.34"/>
<rect x="96" y="240" width="108" height="104" fill="#ffffff" opacity="0.2"/></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

const FIXTURES: Record<string, { file: string; url: string; globals?: Record<string, unknown> }> = {
  'jsonld-apparel': {
    file: 'jsonld-apparel.html',
    url: 'https://www.zara.com/in/en/leather-effect-jacket-p07840321.html',
  },
  'og-and-dom': { file: 'og-and-dom.html', url: 'https://www2.hm.com/en_in/productpage.1234567001.html' },
  'embedded-state': {
    file: 'embedded-state.html',
    url: 'https://www.myntra.com/jeans/roadster/roadster-men-blue-jeans/2296012/buy',
  },
  microdata: { file: 'microdata.html', url: 'https://www.example-outdoors.fr/p/trail-shoes-8845' },
  'dom-only': { file: 'dom-only.html', url: 'https://www.studiobeauty.in/product/velvet-matte-lipstick' },
  'amazon-like': { file: 'amazon-like.html', url: 'https://www.amazon.in/dp/B0CHX1W1XY' },
  'listing-page': { file: 'listing-page.html', url: 'https://www.example-store.com/women/jackets' },
};

const store: Record<string, unknown> = {};

function installChrome(detectResult: unknown, fixtureUrl: string): void {
  (globalThis as unknown as { chrome: unknown }).chrome = {
    tabs: {
      query: async () => [{ id: 1, url: fixtureUrl }],
      create: async ({ url }: { url: string }) => {
        window.open(url, '_blank');
      },
      sendMessage: (_tabId: number, message: { type: string }, callback: (value: unknown) => void) => {
        callback(message.type === MESSAGE.PING ? { ready: true } : detectResult);
      },
    },
    scripting: { executeScript: async () => [{ result: {} }] },
    storage: {
      local: {
        get: async (key: string) => ({ [key]: store[key] }),
        set: async (values: Record<string, unknown>) => {
          Object.assign(store, values);
        },
        remove: async (key: string) => {
          delete store[key];
        },
      },
    },
    runtime: {
      lastError: undefined,
      sendMessage: async () => undefined,
      getURL: (path: string) => `/${path}`,
    },
  };
}

// --------------------------------------------------------------- popup ----

async function renderPopup(): Promise<void> {
  const selected = params.get('f') ?? 'jsonld-apparel';
  const fixture = FIXTURES[selected] ?? FIXTURES['jsonld-apparel'];

  const html = await fetch(`/tests/fixtures/${fixture.file}`).then((response) => response.text());
  const doc = new DOMParser().parseFromString(html, 'text/html');

  const result = runDetection({
    doc,
    url: fixture.url,
    hostname: normaliseHostname(fixture.url),
    pageGlobals: fixture.globals ?? {},
  });

  // Applied after detection so the pipeline's own URL handling is unaffected.
  if (result.product) result.product.imageUrl = placeholderImage(0);

  installChrome(result, fixture.url);

  // Signed in by default, since that is the state the popup is normally used
  // in. Pass `?auth=out` to preview the sign-in panel instead.
  if (params.get('auth') !== 'out') {
    store['stockwatch:session'] = {
      accessToken: 'preview',
      refreshToken: 'preview',
      email: 'shopper@example.com',
    };
  }
  console.info(`[preview] popup fixture "${selected}"`, result);

  document.getElementById('frame')?.setAttribute('data-mode', 'popup');
  await import('../src/popup/main');
}

// ----------------------------------------------------------- dashboard ----

/** Canned API responses, shaped exactly like the FastAPI schemas. */
function fakeBackend(): void {
  const products = [
    product(
      1, 'Leather Effect Jacket', 'Zara', '12990.00', '15990.00', 'in_stock',
      [
        ['S', 'in_stock', false],
        ['M', 'out_of_stock', true],
        ['L', 'out_of_stock', true],
        ['XL', 'in_stock', false],
      ],
      { checkedMinutesAgo: 6 },
    ),
    product(
      2, 'Roadster Men Blue Slim Fit Jeans', 'Myntra', '1149.00', '2299.00', 'in_stock',
      [
        ['30', 'out_of_stock', true],
        ['32', 'in_stock', false],
        ['34', 'in_stock', false],
      ],
      { atLowest: true, checkedMinutesAgo: 21 },
    ),
    product(
      3, 'Velvet Matte Lipstick', 'Studio Beauty', '899.00', '1299.00', 'out_of_stock',
      [
        ['Shade 01', 'in_stock', false],
        ['Shade 03', 'out_of_stock', true],
      ],
      { checkedMinutesAgo: 34 },
    ),
    product(4, 'Oversized Hoodie', 'H&M', '1999.00', '2999.00', 'in_stock', [], {
      checkedMinutesAgo: 95,
    }),
    product(5, 'Acme Studio Wireless Headphones', 'Amazon India', '8499.00', '12999.00', 'in_stock', [], {
      atLowest: true,
      checkedMinutesAgo: 48,
    }),
  ];

  const notifications = [
    {
      id: 1,
      type: 'STOCK_AVAILABLE',
      priority: 'high',
      title: 'M is back in stock',
      message: 'Leather Effect Jacket is available again in M at ₹12,990.',
      price: '12990.00',
      previous_price: null,
      currency: 'INR',
      created_at: new Date(Date.now() - 3.6e6).toISOString(),
      read_at: null,
      tracked_product_id: 1,
      product_name: 'Leather Effect Jacket',
      product_url: 'https://www.zara.com/',
      product_image_url: null,
      variant_name: 'M',
    },
    {
      id: 2,
      type: 'PRICE_DROP',
      priority: 'normal',
      title: 'Price drop: Roadster Men Blue Slim Fit Jeans',
      message: 'Down from ₹1,499 to ₹1,149.',
      price: '1149.00',
      previous_price: '1499.00',
      currency: 'INR',
      created_at: new Date(Date.now() - 9e7).toISOString(),
      read_at: new Date().toISOString(),
      tracked_product_id: 2,
      product_name: 'Roadster Men Blue Slim Fit Jeans',
      product_url: 'https://www.myntra.com/',
      product_image_url: null,
      variant_name: null,
    },
  ];

  const original = window.fetch.bind(window);

  window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;

    // Fixture files still come from the dev server.
    if (!url.includes('/api/')) return original(input as RequestInfo, init);

    const json = (body: unknown) =>
      new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

    if (url.includes('/products/overview')) {
      return json({
        tracked_total: products.length,
        tracking_active: products.length,
        in_stock: 4,
        out_of_stock: 1,
        unknown_stock: 0,
        price_drops_7d: 3,
        back_in_stock_7d: 1,
        at_lowest_price: 2,
        unread_notifications: 1,
        total_saved: '11150.00',
        currency: 'INR',
      });
    }
    if (url.includes('/price-history')) {
      const base = Date.now() - 30 * 864e5;
      const prices = [15990, 15990, 14990, 14990, 13490, 13490, 12990, 12990, 11990, 12990];
      return json({
        product_id: 1,
        currency: 'INR',
        range: '30d',
        points: prices.map((price, index) => ({
          price: `${price}.00`,
          recorded_at: new Date(base + index * 3 * 864e5).toISOString(),
        })),
        stats: {
          current: '12990.00',
          previous: '11990.00',
          lowest: '11990.00',
          highest: '15990.00',
          average: '14181.00',
          lowest_7d: '11990.00',
          lowest_30d: '11990.00',
          change_percentage: 8.34,
          below_highest_percentage: -18.76,
          is_at_lowest: false,
        },
      });
    }
    if (url.includes('/notifications')) return json({ items: notifications, total: notifications.length, limit: 50, offset: 0 });
    if (/\/products\/\d+$/.test(url.split('?')[0])) {
      return json({ ...products[0], price_stats: { current: '12990.00', lowest: '11990.00', highest: '15990.00', average: '14181.00', lowest_7d: '11990.00', lowest_30d: '11990.00', previous: '11990.00', change_percentage: 8.3, below_highest_percentage: -18.8, is_at_lowest: false } });
    }
    if (url.includes('/products')) return json({ items: products, total: products.length, limit: 100, offset: 0 });

    return json({ detail: 'ok' });
  }) as typeof window.fetch;
}

function product(
  id: number,
  name: string,
  storeName: string,
  price: string,
  original: string,
  availability: string,
  variants: Array<[string, string, boolean]>,
  options: { atLowest?: boolean; checkedMinutesAgo?: number } = {},
) {
  const current = Number.parseFloat(price);
  const was = Number.parseFloat(original);
  // Only a product actually sitting at its record low earns the badge, so the
  // fixture varies it rather than marking everything.
  const lowest = options.atLowest ? current : Math.round(current * 0.88);
  const checkedMinutesAgo = options.checkedMinutesAgo ?? 12;
  return {
    id,
    url: `https://example.com/p/${id}`,
    name,
    brand: null,
    category: null,
    image_url: placeholderImage(id - 1),
    store: storeName,
    store_slug: storeName.toLowerCase(),
    currency: 'INR',
    current_price: price,
    original_price: original,
    lowest_price: `${lowest}.00`,
    highest_price: original,
    average_price: original,
    discount_percentage: Math.round(((was - current) / was) * 100),
    availability,
    last_checked_at: new Date(Date.now() - checkedMinutesAgo * 60000).toISOString(),
    last_check_status: 'ok',
    consecutive_failures: 0,
    tracking_enabled: id !== 4,
    price_tracking_enabled: true,
    stock_tracking_enabled: true,
    target_price: null,
    notify_email: true,
    notify_browser: true,
    created_at: new Date(Date.now() - id * 864e5).toISOString(),
    updated_at: new Date().toISOString(),
    variants: variants.map(([variantName, stock, watched], index) => ({
      id: id * 100 + index,
      variant_id: variantName,
      variant_name: variantName,
      variant_type: 'size',
      current_stock: stock,
      previous_stock: 'unknown',
      is_watched: watched,
      sku: null,
      price: null,
      last_in_stock_at: null,
    })),
  };
}

async function renderDashboard(): Promise<void> {
  installChrome(null, 'https://example.com');
  store['stockwatch:session'] = {
    accessToken: 'preview',
    refreshToken: 'preview',
    email: 'shopper@example.com',
  };
  fakeBackend();

  const frame = document.getElementById('frame');
  frame?.setAttribute('data-mode', 'dashboard');
  await import('../src/dashboard/main');
}

if (view === 'dashboard') {
  await renderDashboard();
} else {
  await renderPopup();
}
