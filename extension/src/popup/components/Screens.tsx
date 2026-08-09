/** Loading, empty and failure states. A polished tool is judged on these. */

import type { ReactNode } from 'react';

import { Spinner } from './ui';

function Frame({ children }: { children: ReactNode }) {
  return <div className="px-8 py-12 text-center">{children}</div>;
}

export function LoadingScreen() {
  return (
    <div className="sw-fade">
      <div className="sw-skeleton w-full" style={{ height: 268 }} />
      <div className="space-y-3 px-5 py-5">
        <div className="sw-skeleton h-2 w-16" />
        <div className="sw-skeleton h-3 w-3/4" />
        <div className="sw-skeleton h-3 w-24" />
      </div>
      <div className="grid grid-cols-5 gap-px px-5">
        {[0, 1, 2, 3, 4].map((index) => (
          <div key={index} className="sw-skeleton h-[34px]" />
        ))}
      </div>
      <p className="sw-label mt-6 flex items-center justify-center gap-2 pb-6">
        <Spinner className="h-2.5 w-2.5" />
        Reading this page
      </p>
    </div>
  );
}

export function NotDetectedScreen({ storeName, onRetry }: { storeName?: string; onRetry: () => void }) {
  return (
    <Frame>
      <h2 className="sw-label-strong">No product here</h2>
      <p className="mt-4 text-[12px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
        {storeName ? (
          <>
            We read <span style={{ color: 'var(--sw-fg)' }}>{storeName}</span>, but this looks like a listing,
            search or home page.
          </>
        ) : (
          <>This does not look like a product page.</>
        )}{' '}
        Open a product and try again.
      </p>
      <button type="button" onClick={onRetry} className="sw-button-ghost mt-6">
        Scan again
      </button>
    </Frame>
  );
}

export function MessageScreen({
  title,
  message,
  actionLabel,
  onAction,
}: {
  title: string;
  message: string;
  actionLabel?: string;
  onAction?: () => void;
}) {
  return (
    <Frame>
      <h2 className="sw-label-strong">{title}</h2>
      <p className="mt-4 text-[12px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
        {message}
      </p>
      {onAction && actionLabel ? (
        <button type="button" onClick={onAction} className="sw-button-ghost mt-6">
          {actionLabel}
        </button>
      ) : null}
    </Frame>
  );
}
