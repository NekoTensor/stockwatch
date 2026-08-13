/**
 * The dashboard.
 *
 * Structured like a shop's own account area rather than an analytics tool:
 * a wordmark, a row of section links, and then product images doing the work.
 * Numbers are set in the same quiet type as everything else.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  ApiError,
  api,
  getSession,
  logout,
  type NotificationOut,
  type Overview,
  type Session,
  type TrackedProductOut,
} from '../lib/api';
import { formatPrice } from '../lib/price';
import { AuthPanel } from '../popup/components/AuthPanel';
import { Spinner, ThemeToggle, Wordmark } from '../popup/components/ui';
import { NotificationSettings } from './components/NotificationSettings';
import { ProductCard } from './components/ProductCard';
import { ProductPanel } from './components/ProductPanel';

type Tab =
  | 'overview'
  | 'tracked'
  | 'price-drops'
  | 'back-in-stock'
  | 'lowest'
  | 'notifications'
  | 'settings';

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'overview', label: 'Overview' },
  { id: 'tracked', label: 'Tracked' },
  { id: 'price-drops', label: 'Price drops' },
  { id: 'back-in-stock', label: 'In stock' },
  { id: 'lowest', label: 'Lowest price' },
  { id: 'notifications', label: 'Alerts' },
  { id: 'settings', label: 'Settings' },
];

const SORTS = [
  { id: 'recent', label: 'Recently added' },
  { id: 'updated', label: 'Recently updated' },
  { id: 'price_drop', label: 'Biggest drop' },
  { id: 'discount', label: 'Highest discount' },
  { id: 'lowest_price', label: 'Lowest price' },
  { id: 'name', label: 'Name' },
] as const;

/** Each tab is a saved filter over the same endpoint. */
const TAB_FILTER: Record<Tab, string | undefined> = {
  overview: undefined,
  tracked: 'all',
  'price-drops': 'price_drop',
  'back-in-stock': 'in_stock',
  lowest: 'lowest_price',
  notifications: undefined,
  settings: undefined,
};

export default function App() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [tab, setTab] = useState<Tab>('overview');
  const [sort, setSort] = useState<(typeof SORTS)[number]['id']>('recent');
  const [search, setSearch] = useState('');

  const [overview, setOverview] = useState<Overview | null>(null);
  const [products, setProducts] = useState<TrackedProductOut[]>([]);
  const [notifications, setNotifications] = useState<NotificationOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [open, setOpen] = useState<TrackedProductOut | null>(null);

  useEffect(() => {
    void getSession().then(setSession);
  }, []);

  const load = useCallback(async () => {
    if (!session) return;
    setLoading(true);
    setError(null);

    try {
      if (tab === 'notifications') {
        const page = await api.notifications({ limit: 100 });
        setNotifications(page.items);
      } else {
        const [list, stats] = await Promise.all([
          api.listProducts({ status: TAB_FILTER[tab] ?? 'all', sort, search: search || undefined, limit: 100 }),
          api.overview(),
        ]);
        setProducts(list.items);
        setOverview(stats);
      }
    } catch (caught) {
      const apiError = caught as ApiError;
      if (apiError.isAuthError) {
        setSession(null);
        return;
      }
      setError(apiError.message);
    } finally {
      setLoading(false);
    }
  }, [session, tab, sort, search]);

  useEffect(() => {
    void load();
  }, [load]);

  const currency = overview?.currency ?? products[0]?.currency ?? undefined;

  const act = async (action: () => Promise<unknown>) => {
    try {
      await action();
      await load();
    } catch (caught) {
      setError((caught as ApiError).message);
    }
  };

  // Defined once and spread into every grid. They used to be written inline at
  // the one call site that had them, which is how the Overview tab ended up
  // rendering cards whose buttons were bound to `() => undefined` — visibly
  // clickable, silently inert.
  const cardActions = {
    onCheck: async (product: TrackedProductOut) => {
      setCheckingId(product.id);
      try {
        await act(() => api.checkNow(product.id));
      } finally {
        setCheckingId(null);
      }
    },
    onPauseToggle: (product: TrackedProductOut) =>
      act(() => (product.tracking_enabled ? api.pauseProduct(product.id) : api.resumeProduct(product.id))),
    onDelete: (product: TrackedProductOut) => act(() => api.deleteProduct(product.id)),
  };

  if (session === undefined) {
    return (
      <Shell>
        <div className="flex items-center justify-center py-32">
          <Spinner className="h-4 w-4" />
        </div>
      </Shell>
    );
  }

  if (!session) {
    return (
      <Shell>
        <div className="mx-auto max-w-[420px] py-20">
          <AuthPanel onDone={() => void getSession().then(setSession)} />
        </div>
      </Shell>
    );
  }

  return (
    <Shell
      nav={
        <nav className="flex flex-wrap items-center gap-x-7 gap-y-2">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => setTab(entry.id)}
              className={`sw-nav ${tab === entry.id ? 'sw-nav-active' : ''}`}
            >
              {entry.label}
              {entry.id === 'notifications' && overview?.unread_notifications
                ? ` (${overview.unread_notifications})`
                : ''}
            </button>
          ))}
        </nav>
      }
      account={
        <div className="flex items-center gap-6">
          <ThemeToggle variant="segmented" />
          <span className="sw-label max-w-[220px] truncate">{session.email}</span>
          <button
            type="button"
            onClick={async () => {
              await logout();
              setSession(null);
            }}
            className="sw-label underline underline-offset-4"
          >
            Sign out
          </button>
        </div>
      }
    >
      {error ? (
        <p className="mb-8 text-[12px]" style={{ color: 'var(--sw-sale)' }}>
          {error}
        </p>
      ) : null}

      {tab === 'overview' ? (
        <OverviewSection
          overview={overview}
          products={products}
          currency={currency}
          loading={loading}
          checkingId={checkingId}
          onOpen={setOpen}
          {...cardActions}
        />
      ) : tab === 'settings' ? (
        <NotificationSettings />
      ) : tab === 'notifications' ? (
        <NotificationsSection
          notifications={notifications}
          loading={loading}
          onMarkRead={() => act(() => api.markRead())}
        />
      ) : (
        <>
          <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search"
              className="sw-input max-w-[240px]"
            />
            <div className="flex flex-wrap items-center gap-5">
              <span className="sw-label">Sort</span>
              {SORTS.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setSort(option.id)}
                  className={`sw-nav ${sort === option.id ? 'sw-nav-active' : ''}`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <ProductGrid
            products={products}
            loading={loading}
            checkingId={checkingId}
            onOpen={setOpen}
            {...cardActions}
          />
        </>
      )}

      {open ? (
        <ProductPanel
          product={open}
          onClose={() => setOpen(null)}
          onChanged={() => void load()}
        />
      ) : null}
    </Shell>
  );
}

function Shell({
  children,
  nav,
  account,
}: {
  children: React.ReactNode;
  nav?: React.ReactNode;
  account?: React.ReactNode;
}) {
  return (
    <div className="min-h-screen">
      <header
        className="sticky top-0 z-30 px-8 py-5 lg:px-14"
        style={{ background: 'var(--sw-bg)', borderBottom: '1px solid var(--sw-line)' }}
      >
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-4">
          <Wordmark />
          {nav}
          {account}
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-8 py-12 lg:px-14">{children}</main>
    </div>
  );
}

interface CardActions {
  onCheck: (product: TrackedProductOut) => void;
  onPauseToggle: (product: TrackedProductOut) => void;
  onDelete: (product: TrackedProductOut) => void;
}

function OverviewSection({
  overview,
  products,
  currency,
  loading,
  checkingId,
  onOpen,
  onCheck,
  onPauseToggle,
  onDelete,
}: {
  overview: Overview | null;
  products: TrackedProductOut[];
  currency: string | undefined;
  loading: boolean;
  checkingId: number | null;
  onOpen: (product: TrackedProductOut) => void;
} & CardActions) {
  const recent = useMemo(() => products.slice(0, 8), [products]);

  if (!overview) {
    return <div className="sw-skeleton h-24 w-full" />;
  }

  return (
    <>
      <dl
        className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6"
        style={{ borderTop: '1px solid var(--sw-line)', borderLeft: '1px solid var(--sw-line)' }}
      >
        <Metric label="Tracked" value={String(overview.tracked_total)} />
        <Metric label="In stock" value={String(overview.in_stock)} />
        <Metric label="Out of stock" value={String(overview.out_of_stock)} />
        <Metric label="At lowest" value={String(overview.at_lowest_price)} />
        <Metric label="Drops · 7 days" value={String(overview.price_drops_7d)} />
        <Metric label="Potential saving" value={formatPrice(Number.parseFloat(overview.total_saved), currency)} />
      </dl>

      <section className="mt-16">
        <h2 className="sw-label mb-6">Recently added</h2>
        <ProductGrid
          products={recent}
          loading={loading}
          checkingId={checkingId}
          onOpen={onOpen}
          onCheck={onCheck}
          onPauseToggle={onPauseToggle}
          onDelete={onDelete}
        />
      </section>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="px-6 py-7"
      style={{ borderRight: '1px solid var(--sw-line)', borderBottom: '1px solid var(--sw-line)' }}
    >
      <dt className="sw-label">{label}</dt>
      <dd className="mt-3 text-[22px] leading-none">{value}</dd>
    </div>
  );
}

function ProductGrid({
  products,
  loading,
  checkingId,
  onOpen,
  onCheck,
  onPauseToggle,
  onDelete,
}: {
  products: TrackedProductOut[];
  loading: boolean;
  checkingId: number | null;
  onOpen: (product: TrackedProductOut) => void;
} & CardActions) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-x-6 gap-y-12 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
        {[0, 1, 2, 3, 4].map((index) => (
          <div key={index}>
            <div className="sw-skeleton w-full" style={{ aspectRatio: '3 / 4' }} />
            <div className="sw-skeleton mt-3 h-2 w-16" />
            <div className="sw-skeleton mt-2 h-3 w-full" />
          </div>
        ))}
      </div>
    );
  }

  if (!products.length) return <EmptyState />;

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-12 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {products.map((product) => (
        <ProductCard
          key={product.id}
          product={product}
          busy={checkingId === product.id}
          onOpen={onOpen}
          onCheck={onCheck}
          onPauseToggle={onPauseToggle}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}

function NotificationsSection({
  notifications,
  loading,
  onMarkRead,
}: {
  notifications: NotificationOut[];
  loading: boolean;
  onMarkRead: () => void;
}) {
  if (loading) return <div className="sw-skeleton h-40 w-full" />;

  if (!notifications.length) {
    return (
      <p className="py-20 text-center text-[12px]" style={{ color: 'var(--sw-muted)' }}>
        No alerts yet. They appear here the moment something you track changes.
      </p>
    );
  }

  return (
    <>
      <div className="mb-6 flex justify-end">
        <button type="button" onClick={onMarkRead} className="sw-label underline underline-offset-4">
          Mark all read
        </button>
      </div>

      <ul style={{ borderTop: '1px solid var(--sw-line)' }}>
        {notifications.map((notification) => (
          <li
            key={notification.id}
            className="flex items-start gap-5 py-5"
            style={{ borderBottom: '1px solid var(--sw-line)' }}
          >
            {notification.product_image_url ? (
              <img
                src={notification.product_image_url}
                alt=""
                className="w-[56px] shrink-0 object-cover"
                style={{ aspectRatio: '3 / 4', background: 'var(--sw-surface)' }}
              />
            ) : null}

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="sw-label">{notification.type.replace(/_/g, ' ')}</span>
                {!notification.read_at ? (
                  <span className="sw-label" style={{ color: 'var(--sw-sale)' }}>
                    New
                  </span>
                ) : null}
                <span className="sw-label">
                  {new Date(notification.created_at).toLocaleString(undefined, {
                    day: 'numeric',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
              </div>
              <p className="mt-1.5 text-[13px] leading-snug">{notification.title}</p>
              <p className="mt-1 text-[12px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
                {notification.message}
              </p>
            </div>

            {notification.product_url ? (
              <a
                href={notification.product_url}
                target="_blank"
                rel="noopener noreferrer"
                className="sw-label shrink-0 underline underline-offset-4"
              >
                Open
              </a>
            ) : null}
          </li>
        ))}
      </ul>
    </>
  );
}

function EmptyState() {
  return (
    <div className="py-20 text-center">
      <p className="sw-label-strong">Nothing tracked yet</p>
      <p className="mx-auto mt-4 max-w-[420px] text-[12px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
        Open a product page on any shop, click the StockWatch icon, and choose the sizes you want to hear about.
      </p>
    </div>
  );
}
