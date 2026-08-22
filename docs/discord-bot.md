# The Discord bot

StockWatch already posts alerts to a webhook you paste in from your own channel
settings. The bot is the other half: it messages **people**, not channels, so
someone can link their account once and be told about a restock wherever they
are — no webhook, no setup per user.

Both work at the same time. A user with a webhook keeps getting channel posts;
a user who links their Discord account gets a direct message instead.

## What it does

| Command | |
|---|---|
| `/link <code>` | Connects this Discord account to a StockWatch account |
| `/unlink` | Stops alerts to this Discord account |
| `/watching` | The ten most recent products being tracked, and their stock |

Every reply is ephemeral — visible only to the person who ran it. A link code is
a credential while it lives, and nobody else in the channel needs to see it.

## Setting it up

**1. Create the application.** In the [Discord developer
portal](https://discord.com/developers/applications): New Application → Bot →
Reset Token, and copy the token. Put it in `.env`:

```bash
DISCORD_BOT_TOKEN=your-token-here
```

**2. No privileged intents.** Leave Message Content, Server Members and Presence
switched **off**. The bot reads nothing it is not directly handed — it only
answers slash commands and sends direct messages — and needing no privileged
intent means no review and no reason for anyone to distrust it.

**3. Invite it.** OAuth2 → URL Generator, scopes `bot` and
`applications.commands`, and no permissions beyond the default. Slash commands
and DMs need nothing more. Open the generated URL and add it to a server.

A user must share at least one server with the bot before Discord will let it
DM them — that is Discord's rule, not ours, and it is why the invite matters
even though the alerts are private.

**4. Run it.**

```bash
docker compose --profile discord up -d bot
```

It is behind a profile because it is optional: without a token, everything else
runs exactly as before and alerts go by browser and email.

## Linking an account

1. In the StockWatch dashboard, generate a code (`POST /api/auth/discord/link-code`).
2. In Discord, run `/link ABCD1234`.

The code is issued to a signed-in session and redeemed from inside Discord, so
holding both ends is what proves the two accounts are the same person. Codes
last 15 minutes, work once, and generating a new one immediately retires the
old — a mistyped code should stop working, not linger as a second live one.

Asking people to paste their Discord user id instead would prove nothing: ids
are public, so anyone could claim anyone's alerts.

## How delivery works

A direct message needs the gateway connection, and only the bot process has
one. So the worker, which raises the alert, deliberately leaves DM-bound
notifications unsent — no error recorded, because nothing failed — and the bot
picks them up on its next poll.

```
worker  →  notification row (discord_sent_at NULL)  →  bot poll  →  DM
```

Two consequences worth knowing:

- **Nothing older than six hours is delivered.** A bot that was down overnight
  comes back and says what is true now rather than replaying yesterday into
  somebody's DMs. A restock from yesterday is not news anyway.
- **A failed DM is not retried.** If someone's privacy settings block us, the
  reason is recorded on the notification and it is marked done. Retrying every
  twenty seconds forever would achieve nothing except rate limits.

## Running exactly one

Two gateway connections on one token means every command answered twice and
every alert delivered twice. If you scale anything, do not scale this.

## What it deliberately does not do yet

`/track <url>` is not a command. Tracking takes a user-supplied URL that the
server then fetches, and that path needs its input validated before it is
exposed to anyone in a Discord server — see the open SSRF work. Until then,
tracking happens through the extension, where the URL is a page the user is
already on.
