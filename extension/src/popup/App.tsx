/**
 * Popup shell.
 *
 * One job: take whatever the detection pipeline returned and render the honest
 * version of it — found, partly found, or not a product page.
 */

import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { getSession, type Session } from '../lib/api';
import { normaliseHostname } from '../lib/url';
import { identifyStore } from '../stores/registry';
import { AuthPanel } from './components/AuthPanel';
import { DetectionDetails } from './components/DetectionDetails';
import { ProductHero } from './components/ProductHero';
import { LoadingScreen, MessageScreen, NotDetectedScreen } from './components/Screens';
import { TrackingPanel } from './components/TrackingPanel';
import { VariantGrid, variantGroupLabel } from './components/VariantGrid';
import { ThemeToggle, Wordmark } from './components/ui';
import { useDetection } from './state/useDetection';

function Header({ right }: { right?: ReactNode }) {
  return (
    <header className="flex items-center justify-between px-5 py-3.5" style={{ borderBottom: '1px solid var(--sw-line)' }}>
      <Wordmark />
      {right}
    </header>
  );
}

function openDashboard() {
  void chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html') });
}

export default function App() {
  const { phase, result, tab, existingDraft, message, reload } = useDetection();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [showAuth, setShowAuth] = useState(false);
  const [trackedNow, setTrackedNow] = useState(false);

  const product = result?.product;

  useEffect(() => {
    void getSession().then(setSession);
  }, []);

  // Pre-select the options a shopper most likely wants alerts for: the ones
  // that are sold out. That is the whole point of a restock tracker.
  useEffect(() => {
    if (!product) return;
    if (existingDraft) {
      setSelected(new Set(existingDraft.variantIds));
      return;
    }
    const soldOut = product.variants.filter((variant) => variant.availability === 'out_of_stock');
    setSelected(new Set(soldOut.map((variant) => variant.id)));
  }, [product, existingDraft]);

  const storeName = useMemo(() => {
    if (product) return product.store;
    if (!tab?.url) return undefined;
    return identifyStore(normaliseHostname(tab.url)).name;
  }, [product, tab?.url]);

  const toggle = useCallback((id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  if (showAuth) {
    return (
      <>
        <Header />
        <AuthPanel
          onDone={() => {
            setShowAuth(false);
            void getSession().then(setSession);
          }}
          onCancel={() => setShowAuth(false)}
        />
      </>
    );
  }

  if (phase === 'loading' || session === undefined) {
    return (
      <>
        <Header />
        <LoadingScreen />
      </>
    );
  }

  if (phase === 'unsupported') {
    return (
      <>
        <Header />
        <MessageScreen title="Nothing to read" message={message ?? 'This page cannot be inspected.'} />
      </>
    );
  }

  if (phase === 'error') {
    return (
      <>
        <Header />
        <MessageScreen
          title="Detection failed"
          message={message ?? 'Something went wrong.'}
          actionLabel="Try again"
          onAction={reload}
        />
      </>
    );
  }

  if (!result || !product || result.status === 'not_a_product') {
    return (
      <>
        <Header right={<span className="sw-label truncate">{storeName}</span>} />
        <NotDetectedScreen storeName={storeName} onRetry={reload} />
        <Footer session={session} onSignIn={() => setShowAuth(true)} />
      </>
    );
  }

  const partial = result.status === 'partial';
  const variants = product.variants;

  return (
    <>
      <Header
        right={<span className="sw-label">{partial ? 'Partly detected' : 'Detected'}</span>}
      />

      <ProductHero product={product} />

      {partial && result.missing.length ? (
        <div className="sw-rule px-5 py-3">
          <p className="text-[11px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
            Could not read: {result.missing.join(', ').toLowerCase()}.
            {product.currentPrice !== undefined ? ' Price tracking still works.' : ''}
          </p>
        </div>
      ) : null}

      {variants.length ? (
        <section className="sw-rule px-5 py-4">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="sw-label">{variantGroupLabel(variants)}</h2>
            <span className="sw-label">{selected.size ? `${selected.size} selected` : 'Select'}</span>
          </div>
          <VariantGrid variants={variants} selected={selected} onToggle={toggle} />
        </section>
      ) : (
        <section className="sw-rule px-5 py-3">
          <p className="text-[11px]" style={{ color: 'var(--sw-muted)' }}>
            No sizes or options found — the product is tracked as a whole.
          </p>
        </section>
      )}

      <TrackingPanel
        product={product}
        selectedVariantIds={[...selected]}
        signedIn={Boolean(session)}
        alreadyTracked={trackedNow}
        onNeedsAuth={() => setShowAuth(true)}
        onTracked={() => setTrackedNow(true)}
      />

      <DetectionDetails result={result} />
      <Footer session={session} onSignIn={() => setShowAuth(true)} />
    </>
  );
}

function Footer({ session, onSignIn }: { session: Session | null; onSignIn: () => void }) {
  return (
    <div className="sw-rule flex items-center justify-between gap-3 px-5 py-3">
      <div className="flex items-center gap-4">
        <button type="button" onClick={openDashboard} className="sw-label underline underline-offset-4">
          Dashboard
        </button>
        <ThemeToggle />
      </div>
      {session ? (
        <span className="sw-label max-w-[150px] truncate">{session.email}</span>
      ) : (
        <button type="button" onClick={onSignIn} className="sw-label underline underline-offset-4">
          Sign in
        </button>
      )}
    </div>
  );
}
