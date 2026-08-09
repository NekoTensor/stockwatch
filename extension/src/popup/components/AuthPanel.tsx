/**
 * Sign in / create account, inside the popup.
 *
 * The extension never stores a password — it exchanges one for tokens and keeps
 * only those. The API base URL is editable here because a self-hosted backend
 * is the expected deployment.
 */

import { useEffect, useState } from 'react';

import { ApiError, getSettings, login, register, setBaseUrl } from '../../lib/api';
import { Spinner } from './ui';

export function AuthPanel({ onDone, onCancel }: { onDone: () => void; onCancel?: () => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showServer, setShowServer] = useState(false);
  const [server, setServer] = useState('');

  useEffect(() => {
    void getSettings().then((settings) => setServer(settings.baseUrl));
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      if (showServer && server.trim()) await setBaseUrl(server);
      if (mode === 'login') await login(email.trim(), password);
      else await register(email.trim(), password);
      onDone();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="sw-fade px-5 py-6">
      <h2 className="sw-label-strong">{mode === 'login' ? 'Sign in' : 'Create account'}</h2>
      <p className="mt-3 text-[11px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
        Tracking runs on the server, so your alerts keep working with the browser closed.
      </p>

      <div className="mt-5 space-y-4">
        <div>
          <label htmlFor="email" className="sw-label mb-1 block">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="sw-input"
          />
        </div>

        <div>
          <label htmlFor="password" className="sw-label mb-1 block">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={mode === 'register' ? 10 : undefined}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="sw-input"
          />
          {mode === 'register' ? (
            <p className="mt-1.5 text-[10px]" style={{ color: 'var(--sw-faint)' }}>
              At least 10 characters, mixing letters with numbers or symbols.
            </p>
          ) : null}
        </div>

        {showServer ? (
          <div className="sw-fade">
            <label htmlFor="server" className="sw-label mb-1 block">
              Server
            </label>
            <input
              id="server"
              value={server}
              onChange={(event) => setServer(event.target.value)}
              placeholder="http://localhost:8000/api"
              className="sw-input"
            />
          </div>
        ) : null}
      </div>

      {error ? (
        <p className="mt-4 text-[11px] leading-relaxed" style={{ color: 'var(--sw-sale)' }}>
          {error}
        </p>
      ) : null}

      <button type="submit" disabled={busy} className="sw-button mt-6">
        {busy ? <Spinner className="mr-2 h-3 w-3" /> : null}
        {mode === 'login' ? 'Sign in' : 'Create account'}
      </button>

      <div className="mt-4 flex items-center justify-between">
        <button
          type="button"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login');
            setError(null);
          }}
          className="sw-label underline underline-offset-4"
        >
          {mode === 'login' ? 'Create account' : 'I have an account'}
        </button>

        <button type="button" onClick={() => setShowServer((value) => !value)} className="sw-label">
          {showServer ? 'Hide server' : 'Server'}
        </button>
      </div>

      {onCancel ? (
        <button type="button" onClick={onCancel} className="sw-label mt-4 w-full text-center">
          Back
        </button>
      ) : null}
    </form>
  );
}
