/**
 * Where alerts go.
 *
 * Three switches and one URL field. The webhook is write-only from the client's
 * point of view — the server reports whether one is configured but never sends
 * it back, so this shows a masked placeholder rather than pretending to
 * round-trip a credential.
 */

import { useEffect, useState } from 'react';

import { api, type AccountOut } from '../../lib/api';
import { Checkbox, Spinner } from '../../popup/components/ui';

export function NotificationSettings() {
  const [account, setAccount] = useState<AccountOut | null>(null);
  const [webhook, setWebhook] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void api
      .account()
      .then(setAccount)
      .catch((caught) => setError((caught as Error).message));
  }, []);

  const patch = async (payload: Parameters<typeof api.updateAccount>[0]) => {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.updateAccount(payload);
      setAccount(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
      if ('discord_webhook_url' in payload) setWebhook('');
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (!account) {
    return <div className="sw-skeleton h-40 w-full max-w-[560px]" />;
  }

  return (
    <div className="max-w-[560px]">
      <h2 className="sw-label mb-5">Where alerts go</h2>

      <Checkbox
        checked={account.browser_notifications}
        onChange={(value) => patch({ browser_notifications: value })}
        label="Browser notifications"
        hint="Raised by the extension while your browser is open"
      />
      <Checkbox
        checked={account.email_notifications}
        onChange={(value) => patch({ email_notifications: value })}
        label="Email"
        hint="Sent to your account address"
      />
      <Checkbox
        checked={account.discord_notifications}
        onChange={(value) => patch({ discord_notifications: value })}
        label="Discord"
        hint={
          account.discord_configured
            ? 'Posted to your webhook'
            : 'Add a webhook below to enable this'
        }
      />

      <div className="sw-rule mt-8 pt-6">
        <h3 className="sw-label mb-2">Discord webhook</h3>
        <p className="mb-4 text-[12px] leading-relaxed" style={{ color: 'var(--sw-muted)' }}>
          In Discord: <strong>Server settings → Integrations → Webhooks → New webhook</strong>, pick a
          channel, then copy the URL. It grants permission to post in that one channel and nothing else.
        </p>

        <input
          value={webhook}
          onChange={(event) => setWebhook(event.target.value)}
          placeholder={
            account.discord_configured
              ? 'A webhook is set — paste a new one to replace it'
              : 'https://discord.com/api/webhooks/…'
          }
          className="sw-input"
          spellCheck={false}
        />

        <div className="mt-4 flex flex-wrap items-center gap-4">
          <button
            type="button"
            disabled={saving || !webhook.trim()}
            onClick={() => patch({ discord_webhook_url: webhook.trim(), discord_notifications: true })}
            className="sw-button-ghost"
          >
            {saving ? <Spinner className="mr-2 h-3 w-3" /> : null}
            Save webhook
          </button>

          {account.discord_configured ? (
            <button
              type="button"
              onClick={() => patch({ discord_webhook_url: '' })}
              className="sw-label underline underline-offset-4"
              style={{ color: 'var(--sw-sale)' }}
            >
              Remove
            </button>
          ) : null}

          {saved ? <span className="sw-label">Saved</span> : null}
        </div>
      </div>

      {error ? (
        <p className="mt-4 text-[12px]" style={{ color: 'var(--sw-sale)' }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
