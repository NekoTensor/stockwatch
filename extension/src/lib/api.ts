/**
 * The API client.
 *
 * Holds no secrets: the extension authenticates with tokens the user obtained
 * by logging in, and every key that matters (database, Resend, JWT signing)
 * lives on the server. A compromised extension build leaks a session, not the
 * service.
 *
 * Access tokens are short-lived, so a 401 triggers exactly one refresh attempt
 * and a replay — concurrent callers share that attempt rather than each firing
 * their own.
 */

import type { ProductData, Variant } from './types';

const DEFAULT_BASE_URL = 'http://localhost:8000/api';
const STORAGE_KEY = 'stockwatch:session';
const SETTINGS_KEY = 'stockwatch:settings';

export interface Session {
  accessToken: string;
  refreshToken: string;
  email: string;
}

export interface ApiSettings {
  baseUrl: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** True when signing in again is the only way forward. */
  get isAuthError(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

// --------------------------------------------------------------- storage ----

export async function getSettings(): Promise<ApiSettings> {
  const stored = await chrome.storage.local.get(SETTINGS_KEY);
  return { baseUrl: DEFAULT_BASE_URL, ...(stored?.[SETTINGS_KEY] ?? {}) };
}

export async function setBaseUrl(baseUrl: string): Promise<void> {
  const trimmed = baseUrl.trim().replace(/\/+$/, '');
  await chrome.storage.local.set({ [SETTINGS_KEY]: { baseUrl: trimmed || DEFAULT_BASE_URL } });
}

export async function getSession(): Promise<Session | null> {
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  return (stored?.[STORAGE_KEY] as Session | undefined) ?? null;
}

async function saveSession(session: Session): Promise<void> {
  await chrome.storage.local.set({ [STORAGE_KEY]: session });
}

export async function clearSession(): Promise<void> {
  await chrome.storage.local.remove(STORAGE_KEY);
}

// ---------------------------------------------------------------- client ----

interface TokenPair {
  access_token: string;
  refresh_token: string;
}

/** Shared across callers so a burst of 401s produces one refresh, not five. */
let refreshInFlight: Promise<Session | null> | null = null;

async function refreshSession(): Promise<Session | null> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    const session = await getSession();
    if (!session) return null;

    const { baseUrl } = await getSettings();
    try {
      const response = await fetch(`${baseUrl}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: session.refreshToken }),
      });
      if (!response.ok) {
        await clearSession();
        return null;
      }
      const tokens = (await response.json()) as TokenPair;
      const next: Session = {
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
        email: session.email,
      };
      await saveSession(next);
      return next;
    } catch {
      // Network failure is not an auth failure: keep the session so the user is
      // not logged out because their wifi dropped.
      return session;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  { retry = true }: { retry?: boolean } = {},
): Promise<T> {
  const { baseUrl } = await getSettings();
  const session = await getSession();

  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  if (session) headers.set('Authorization', `Bearer ${session.accessToken}`);

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, { ...init, headers });
  } catch (error) {
    throw new ApiError(
      `Could not reach StockWatch at ${baseUrl}. Is the backend running?`,
      0,
      (error as Error).message,
    );
  }

  if (response.status === 401 && retry && session) {
    const refreshed = await refreshSession();
    if (refreshed) return request<T>(path, init, { retry: false });
  }

  if (response.status === 204) return undefined as T;

  const body = await response.json().catch(() => undefined);

  if (!response.ok) {
    const detail = (body as { detail?: unknown } | undefined)?.detail;
    throw new ApiError(
      typeof detail === 'string' ? detail : `Request failed (${response.status}).`,
      response.status,
      detail,
    );
  }

  return body as T;
}

// ------------------------------------------------------------------ auth ----

/**
 * FastAPI returns validation failures as a list of objects, not a string.
 * Surfacing "[object Object]" — or a flat "Something went wrong" — hides the
 * one thing the user needs, which is *which field* it disliked.
 */
function describeDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => {
        if (typeof entry === 'string') return entry;
        const item = entry as { loc?: unknown[]; msg?: string } | null;
        if (!item?.msg) return undefined;
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : undefined;
        const label = typeof field === 'string' && field !== 'body' ? `${field}: ` : '';
        return `${label}${item.msg.replace(/^Value error,\s*/i, '')}`;
      })
      .filter(Boolean);
    if (messages.length) return messages.join(' ');
  }

  return fallback;
}

/**
 * Sign-in and registration bypass `request()` because they must not attach or
 * refresh a token. They still need its error handling: without it a backend
 * that simply is not running surfaces as a bare "Something went wrong", which
 * sends people hunting for a bug in their password.
 */
async function authenticate(path: string, email: string, password: string, fallback: string): Promise<Session> {
  const { baseUrl } = await getSettings();

  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
  } catch (error) {
    throw new ApiError(
      `Could not reach StockWatch at ${baseUrl}. Start the backend, or change the server address below.`,
      0,
      (error as Error).message,
    );
  }

  const body = await response.json().catch(() => undefined);

  if (!response.ok) {
    throw new ApiError(
      describeDetail((body as { detail?: unknown } | undefined)?.detail, fallback),
      response.status,
    );
  }

  const tokens = body as TokenPair;
  const session: Session = { accessToken: tokens.access_token, refreshToken: tokens.refresh_token, email };
  await saveSession(session);
  return session;
}

export function register(email: string, password: string): Promise<Session> {
  return authenticate('/auth/register', email, password, 'Could not create the account.');
}

export function login(email: string, password: string): Promise<Session> {
  return authenticate('/auth/login', email, password, 'Incorrect email or password.');
}

export async function logout(): Promise<void> {
  await clearSession();
}

// -------------------------------------------------------------- products ----

export interface TrackedVariantOut {
  id: number;
  variant_id: string;
  variant_name: string;
  variant_type: Variant['type'];
  current_stock: Variant['availability'];
  previous_stock: Variant['availability'];
  is_watched: boolean;
  sku: string | null;
  price: string | null;
  last_in_stock_at: string | null;
}

export interface TrackedProductOut {
  id: number;
  url: string;
  name: string;
  brand: string | null;
  category: string | null;
  image_url: string | null;
  store: string | null;
  store_slug: string | null;
  currency: string | null;
  current_price: string | null;
  original_price: string | null;
  lowest_price: string | null;
  highest_price: string | null;
  average_price: string | null;
  discount_percentage: number | null;
  /** The retailer's answer: is this product buyable at all. */
  availability: Variant['availability'];
  /** The user's answer: are the sizes they are watching buyable. Shown in the UI. */
  watched_availability: Variant['availability'];
  watched_variant_names: string[];
  last_checked_at: string | null;
  last_check_status: string | null;
  consecutive_failures: number;
  tracking_enabled: boolean;
  price_tracking_enabled: boolean;
  stock_tracking_enabled: boolean;
  target_price: string | null;
  notify_email: boolean;
  notify_browser: boolean;
  created_at: string;
  updated_at: string;
  variants: TrackedVariantOut[];
  verdict: PriceVerdict;
  active_rule_count: number;
}

export type PriceVerdict = 'buy' | 'fair' | 'high' | 'unknown';

export interface PriceStats {
  current: string | null;
  previous: string | null;
  lowest: string | null;
  highest: string | null;
  average: string | null;
  lowest_7d: string | null;
  lowest_30d: string | null;
  highest_30d: string | null;
  average_30d: string | null;
  median_30d: string | null;
  change_percentage: number | null;
  below_highest_percentage: number | null;
  vs_average_percentage: number | null;
  saving_vs_average: string | null;
  percentile: number | null;
  volatility: number | null;
  observations: number;
  is_at_lowest: boolean;
  verdict: PriceVerdict;
  verdict_reason: string;
}

export type StockCondition = 'any' | 'back_in_stock' | 'in_stock' | 'out_of_stock';
export type PriceConditionKind = 'any' | 'below' | 'drops_by_percent' | 'at_lowest' | 'below_average';

export interface WatchRuleOut {
  id: number;
  tracked_product_id: number;
  tracked_variant_id: number | null;
  label: string | null;
  description: string;
  stock_condition: StockCondition;
  price_condition: PriceConditionKind;
  combine: 'all' | 'any';
  price_value: string | null;
  percent_value: string | null;
  notify_browser: boolean;
  notify_email: boolean;
  notify_discord: boolean;
  is_active: boolean;
  cooldown_minutes: number;
  last_triggered_at: string | null;
  trigger_count: number;
  created_at: string;
  variant_name: string | null;
}

export interface WatchRuleInput {
  label?: string | null;
  variant_id?: string | null;
  stock_condition?: StockCondition;
  price_condition?: PriceConditionKind;
  combine?: 'all' | 'any';
  price_value?: number | null;
  percent_value?: number | null;
  notify_browser?: boolean;
  notify_email?: boolean;
  notify_discord?: boolean;
  is_active?: boolean;
  cooldown_minutes?: number;
}

export interface ProductDetail extends TrackedProductOut {
  price_stats: PriceStats;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface AccountOut {
  id: number;
  email: string;
  display_name: string | null;
  email_notifications: boolean;
  browser_notifications: boolean;
  discord_notifications: boolean;
  /** Whether a webhook is set. The URL itself is never sent back. */
  discord_configured: boolean;
}

export interface Overview {
  tracked_total: number;
  tracking_active: number;
  in_stock: number;
  out_of_stock: number;
  unknown_stock: number;
  price_drops_7d: number;
  back_in_stock_7d: number;
  at_lowest_price: number;
  unread_notifications: number;
  total_saved: string;
  currency: string | null;
}

export interface NotificationOut {
  id: number;
  type: string;
  priority: string;
  title: string;
  message: string;
  price: string | null;
  previous_price: string | null;
  currency: string | null;
  created_at: string;
  read_at: string | null;
  tracked_product_id: number;
  product_name: string | null;
  product_url: string | null;
  product_image_url: string | null;
  variant_name: string | null;
}

export interface TrackOptions {
  variantIds: string[];
  trackStock: boolean;
  trackPrice: boolean;
  targetPrice?: number;
  notifyEmail?: boolean;
  notifyBrowser?: boolean;
}

/** Turn a detected product into exactly the payload the API expects. */
export function trackPayload(product: ProductData, options: TrackOptions) {
  return {
    url: product.productUrl,
    name: product.productName ?? 'Untitled product',
    store: product.store,
    store_slug: product.storeId,
    brand: product.brand,
    category: product.category,
    product_id: product.productId,
    sku: product.sku,
    image_url: product.imageUrl,
    currency: product.currency,
    current_price: product.currentPrice,
    original_price: product.originalPrice,
    availability: product.availability,
    variants: product.variants.map((variant) => ({
      id: variant.id,
      name: variant.name,
      type: variant.type,
      availability: variant.availability,
      sku: variant.sku,
      price: variant.price,
    })),
    watched_variant_ids: options.variantIds,
    price_tracking_enabled: options.trackPrice,
    stock_tracking_enabled: options.trackStock,
    target_price: options.targetPrice,
    notify_email: options.notifyEmail ?? true,
    notify_browser: options.notifyBrowser ?? true,
  };
}

export const api = {
  track: (product: ProductData, options: TrackOptions) =>
    request<TrackedProductOut>('/products/track', {
      method: 'POST',
      body: JSON.stringify(trackPayload(product, options)),
    }),

  listProducts: (params: Record<string, string | number | undefined> = {}) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== '') query.set(key, String(value));
    }
    const suffix = query.toString();
    return request<Page<TrackedProductOut>>(`/products${suffix ? `?${suffix}` : ''}`);
  },

  getProduct: (id: number) => request<ProductDetail>(`/products/${id}`),

  updateProduct: (id: number, payload: Record<string, unknown>) =>
    request<TrackedProductOut>(`/products/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  deleteProduct: (id: number) => request<void>(`/products/${id}`, { method: 'DELETE' }),
  pauseProduct: (id: number) => request<TrackedProductOut>(`/products/${id}/pause`, { method: 'POST' }),
  resumeProduct: (id: number) => request<TrackedProductOut>(`/products/${id}/resume`, { method: 'POST' }),
  checkNow: (id: number) => request<TrackedProductOut>(`/products/${id}/check`, { method: 'POST' }),

  priceHistory: (id: number, range: '7d' | '30d' | '90d' | 'all') =>
    request<{
      product_id: number;
      currency: string | null;
      range: string;
      points: Array<{ price: string; recorded_at: string }>;
      stats: PriceStats;
    }>(`/products/${id}/price-history?range=${range}`),

  stockHistory: (id: number) =>
    request<{
      product_id: number;
      points: Array<{
        variant_id: number;
        variant_name: string;
        stock_status: string;
        previous_status: string | null;
        recorded_at: string;
      }>;
    }>(`/products/${id}/stock-history`),

  overview: () => request<Overview>('/products/overview'),

  notifications: (params: { unread_only?: boolean; limit?: number; offset?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.unread_only) query.set('unread_only', 'true');
    if (params.limit) query.set('limit', String(params.limit));
    if (params.offset) query.set('offset', String(params.offset));
    const suffix = query.toString();
    return request<Page<NotificationOut>>(`/notifications${suffix ? `?${suffix}` : ''}`);
  },

  undelivered: () => request<{ items: NotificationOut[] }>('/notifications/undelivered'),

  markDelivered: (ids: number[]) =>
    request<{ detail: string }>('/notifications/delivered', {
      method: 'POST',
      body: JSON.stringify({ notification_ids: ids }),
    }),

  markRead: (ids?: number[]) =>
    request<{ detail: string }>('/notifications/read', {
      method: 'POST',
      body: JSON.stringify({ notification_ids: ids ?? null }),
    }),

  listRules: (productId: number) => request<WatchRuleOut[]>(`/products/${productId}/rules`),

  createRule: (productId: number, payload: WatchRuleInput) =>
    request<WatchRuleOut>(`/products/${productId}/rules`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  updateRule: (productId: number, ruleId: number, payload: WatchRuleInput) =>
    request<WatchRuleOut>(`/products/${productId}/rules/${ruleId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  deleteRule: (productId: number, ruleId: number) =>
    request<void>(`/products/${productId}/rules/${ruleId}`, { method: 'DELETE' }),

  updateAccount: (payload: {
    discord_webhook_url?: string;
    discord_notifications?: boolean;
    email_notifications?: boolean;
    browser_notifications?: boolean;
  }) => request<AccountOut>('/auth/me', { method: 'PATCH', body: JSON.stringify(payload) }),

  account: () => request<AccountOut>('/auth/me'),

  sendTest: (productId?: number) =>
    request<NotificationOut>('/notifications/test', {
      method: 'POST',
      body: JSON.stringify({ tracked_product_id: productId ?? null, send_email: true }),
    }),
};
