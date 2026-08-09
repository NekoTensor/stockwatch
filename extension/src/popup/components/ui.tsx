/** Shared primitives. Deliberately few: the design language is mostly whitespace. */

import { useEffect, useState, type ReactNode } from 'react';

import { THEME_LABEL, THEMES, getTheme, nextTheme, setTheme, type Theme } from '../../lib/theme';

export function Wordmark({ className = '' }: { className?: string }) {
  return (
    <span className={`sw-label-strong select-none ${className}`} style={{ letterSpacing: '0.28em' }}>
      STOCKWATCH
    </span>
  );
}

export function Logo({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" fill="none">
      {/* Three ascending bars - the same mark as the toolbar icon. */}
      <rect x="4" y="19" width="5" height="9" fill="currentColor" />
      <rect x="13.5" y="12" width="5" height="16" fill="currentColor" />
      <rect x="23" y="4" width="5" height="24" fill="currentColor" />
    </svg>
  );
}

export function Spinner({ className = 'h-3 w-3' }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" opacity="0.2" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function CheckIcon({ className = 'h-2.5 w-2.5' }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="none" aria-hidden="true">
      <path d="m3.5 8.5 3 3 6-7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="square" />
    </svg>
  );
}

export function PlusIcon({ open, className = 'h-2.5 w-2.5' }: { open: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 12 12" className={className} fill="none" aria-hidden="true">
      <path d="M0 6h12" stroke="currentColor" strokeWidth="1" />
      {!open && <path d="M6 0v12" stroke="currentColor" strokeWidth="1" />}
    </svg>
  );
}

/** A square checkbox drawn to match the hairline weight of everything else. */
export function Checkbox({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="group flex w-full items-start gap-3 py-2 text-left"
    >
      <span className={`sw-check mt-0.5 ${checked ? 'sw-check-on' : ''}`}>
        {checked ? <CheckIcon /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[12px] leading-tight">{label}</span>
        {hint ? (
          <span className="mt-0.5 block text-[10px]" style={{ color: 'var(--sw-faint)' }}>
            {hint}
          </span>
        ) : null}
      </span>
    </button>
  );
}

export function Section({
  title,
  aside,
  children,
  className = '',
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`sw-rule px-5 py-4 ${className}`}>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="sw-label">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/**
 * Theme control.
 *
 * `segmented` shows all three states at once and is used where there is room;
 * `cycle` is a single button that steps through them, for the popup footer
 * where a three-word control would crowd out the account row.
 */
export function ThemeToggle({ variant = 'cycle' }: { variant?: 'cycle' | 'segmented' }) {
  const [theme, setLocal] = useState<Theme>('system');

  useEffect(() => {
    void getTheme().then(setLocal);
  }, []);

  const choose = (next: Theme) => {
    setLocal(next);
    void setTheme(next);
  };

  if (variant === 'segmented') {
    return (
      <div className="flex items-center gap-3" role="group" aria-label="Theme">
        {THEMES.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={theme === option}
            onClick={() => choose(option)}
            className={`sw-nav ${theme === option ? 'sw-nav-active' : ''}`}
          >
            {THEME_LABEL[option]}
          </button>
        ))}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => choose(nextTheme(theme))}
      title={`Theme: ${THEME_LABEL[theme]} — click to change`}
      aria-label={`Theme: ${THEME_LABEL[theme]}. Click to change.`}
      className="sw-label transition-colors hover:opacity-70"
    >
      {THEME_LABEL[theme]}
    </button>
  );
}

export function StockDot({ status }: { status: 'in_stock' | 'out_of_stock' | 'unknown' }) {
  const colour =
    status === 'in_stock' ? 'var(--sw-stock)' : status === 'out_of_stock' ? 'var(--sw-sale)' : 'var(--sw-faint)';
  return <span className="inline-block h-[5px] w-[5px] shrink-0" style={{ background: colour }} aria-hidden="true" />;
}

export function StockLabel({ status }: { status: 'in_stock' | 'out_of_stock' | 'unknown' }) {
  const text = status === 'in_stock' ? 'In stock' : status === 'out_of_stock' ? 'Out of stock' : 'Stock unknown';
  return (
    <span className="sw-label inline-flex items-center gap-1.5">
      <StockDot status={status} />
      {text}
    </span>
  );
}
