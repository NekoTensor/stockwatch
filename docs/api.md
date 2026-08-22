# API

Base URL `http://localhost:8000/api`. Interactive docs at `/docs`.

Every route except `/health`, `/auth/register`, `/auth/login` and `/auth/refresh`
requires `Authorization: Bearer <access_token>`.

## Auth

Access tokens last 30 minutes, refresh tokens 30 days. The `type` claim is
checked on every decode, so a refresh token presented as an access token is
rejected — without that check a 30-minute credential would quietly become a
30-day one.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/auth/register` | 10-char minimum, must mix letters with numbers or symbols. Rate limited |
| `POST` | `/auth/login` | Same response for a wrong password and an unknown address, so the endpoint cannot enumerate accounts. Rate limited |
| `POST` | `/auth/refresh` | Returns a new pair. Rate limited |
| `GET` | `/auth/me` | |
| `PATCH` | `/auth/me` | Display name, channel preferences |
| `DELETE` | `/auth/me` | 204. Removes the account, its products, history, rules and notifications |
| `POST` | `/auth/discord/link-code` | A code to redeem with the bot's `/link`. Single use, 15 minutes, retires any earlier one |
| `DELETE` | `/auth/discord/link` | 204. Detaches the linked Discord account |

The three rate-limited endpoints answer `429` with a `Retry-After` header and
the usual `detail` message once a caller has had its allowance. Limits are per
address (`AUTH_LOGIN_LIMIT` and friends), and counters live in Redis when
`RATE_LIMIT_STORAGE_URI` says so — in process memory otherwise, which means
per container.

## Products

| Method | Path | Notes |
|---|---|---|
| `POST` | `/products/detect` | Server-side detection for a URL. The extension does not need this — it reads the page it is already on |
| `POST` | `/products/track` | Create or update. Same URL twice updates, so price history stays continuous |
| `GET` | `/products` | `status`, `store`, `search`, `sort`, `limit`, `offset` |
| `GET` | `/products/overview` | Dashboard headline numbers |
| `GET` | `/products/{id}` | Includes `price_stats` |
| `PATCH` | `/products/{id}` | Toggles, target price, watched variants |
| `DELETE` | `/products/{id}` | Cascades to variants, history and alerts |
| `POST` | `/products/{id}/pause` · `/resume` | Resuming schedules a check immediately |
| `POST` | `/products/{id}/check` | Runs inline; still subject to the per-host throttle |
| `GET` | `/products/{id}/price-history` | `range=7d\|30d\|90d\|all` |
| `GET` | `/products/{id}/stock-history` | Transitions only |

**Filters** (`status`): `all`, `in_stock`, `out_of_stock`, `unknown`,
`price_drop`, `lowest_price`, `paused`.

**Sorts**: `recent`, `updated`, `price_drop`, `discount`, `lowest_price`, `name`.

### Track payload

Exactly what the popup builds from a detection result:

```json
{
  "url": "https://www.zara.com/in/en/leather-effect-jacket-p07840321.html",
  "name": "Leather Effect Jacket",
  "store": "Zara",
  "store_slug": "zara",
  "brand": "Zara",
  "currency": "INR",
  "current_price": "12990.00",
  "original_price": "15990.00",
  "availability": "in_stock",
  "variants": [
    { "id": "S", "name": "S", "type": "size", "availability": "in_stock" },
    { "id": "M", "name": "M", "type": "size", "availability": "out_of_stock" }
  ],
  "watched_variant_ids": ["M"],
  "price_tracking_enabled": true,
  "stock_tracking_enabled": true,
  "target_price": "10000.00"
}
```

`watched_variant_ids` empty means "the product as a whole", which is the right
behaviour for something with no variants.

### Availability, twice

Product rows carry two stock fields and they answer different questions:

| Field | Meaning |
|---|---|
| `availability` | What the store says about the product overall |
| `watched_availability` | What the store says about the sizes *this user watches* |

The second is what the interface shows. A jacket whose XXL is in stock is not in
stock to someone watching M, and reporting otherwise trains people to ignore the
label. With no watched variants the two are identical.

## Price intelligence

`GET /products/{id}` returns `price_stats`:

| Field | Meaning |
|---|---|
| `average_30d`, `median_30d`, `highest_30d`, `lowest_30d` | The recent window |
| `lowest`, `highest`, `average` | All of recorded history |
| `saving_vs_average` | Currency saved against `average_30d`, absent when the price is above it |
| `percentile` | Share of past observations that were *cheaper* than now; `0` = best price seen |
| `volatility` | Standard deviation as a percentage of the mean, so it compares across price ranges |
| `observations` | How many checks the rest of this is built on |
| `verdict` | `buy` · `fair` · `high` · `unknown` |
| `verdict_reason` | The sentence behind the verdict |

The verdict stays `unknown` below four observations. A spread of two or three
readings is not a distribution, and dressing one up as advice is how a feature
like this loses its credibility on the first wrong call.

## Watch rules

Rules replace the built-in alert heuristics for a product. Once a product has
one active rule, *only* its rules can raise notifications for it — a user who has
written down what they want should not also receive what we guessed.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/products/{id}/rules` | |
| `POST` | `/products/{id}/rules` | 201 with a generated `description` |
| `PATCH` | `/products/{id}/rules/{rule_id}` | Merged result is re-validated |
| `DELETE` | `/products/{id}/rules/{rule_id}` | 204 |

```json
{
  "variant_id": "M",
  "stock_condition": "back_in_stock",
  "price_condition": "below",
  "price_value": "10000.00",
  "combine": "all",
  "notify_browser": true,
  "notify_email": true,
  "notify_discord": true,
  "cooldown_minutes": 720
}
```

**`stock_condition`**: `any`, `back_in_stock`, `in_stock`, `out_of_stock`.
**`price_condition`**: `any`, `below`, `drops_by_percent`, `at_lowest`,
`below_average`. **`combine`**: `all` or `any`.

`variant_id` is the store's own label (`"M"`), not our row id, and must exist on
the product — an unrecognised one is a 422 rather than a rule that silently
watches everything. Omit it to watch the product as a whole.

Two things worth knowing about evaluation:

- **`back_in_stock` is a transition, not a state.** It fires on the check where
  the variant crosses from out-of-stock to in-stock, and then not again until it
  crosses back. State conditions like `in_stock` would otherwise fire on every
  check forever, which is what `cooldown_minutes` exists to damp.
- **Unknown never triggers.** A failed fetch is not news.

## Notifications

| Method | Path | Notes |
|---|---|---|
| `GET` | `/notifications` | `unread_only`, `limit`, `offset` |
| `GET` | `/notifications/undelivered` | What the extension polls for; excludes test alerts |
| `POST` | `/notifications/delivered` | Acknowledge browser delivery |
| `POST` | `/notifications/read` | Omit ids to mark everything |
| `POST` | `/notifications/test` | Rendered from a real tracked product, flagged `is_test` so it never participates in deduplication |

**Types**: `STOCK_AVAILABLE`, `PRICE_DROP`, `TARGET_PRICE_REACHED`,
`LOWEST_PRICE_REACHED`, `PRICE_INCREASE`, `COMBINED_STOCK_AND_PRICE`.

### Channels

Three, chosen per rule and gated by the account's own switches on `PATCH
/auth/me` (`browser_notifications`, `email_notifications`,
`discord_notifications`, `discord_webhook_url`).

| Channel | Delivery |
|---|---|
| Browser | The extension polls `/notifications/undelivered` |
| Email | Resend, if `RESEND_API_KEY` is set |
| Discord | A channel webhook the user pastes in Settings |

`discord_webhook_url` is write-only: `GET /auth/me` reports
`discord_configured: true` but never returns the URL, because it is a
posting credential and there is no reason for the client to hold it.

Delivery failures are recorded on the notification row (`email_error`,
`discord_error`) and never abort the check that produced it — a webhook Discord
has deleted should cost you one alert, not the run.

Each alert carries the price context that justifies it ("12% below the 30-day
average"), so the notification answers *should I act on this* without requiring
a trip to the dashboard.

## Errors

| Status | Meaning |
|---|---|
| 401 | Missing, malformed, expired, or wrong-type token |
| 404 | Not found *or* not yours — the two are deliberately indistinguishable |
| 409 | Email already registered |
| 422 | Validation failed |
| 502 | `/products/detect` could not fetch the page |
| 500 | Logged with a stack trace; the response body is generic |

## Rate limiting and politeness

Outbound requests to shops are throttled per host across all users, with jitter,
exponential backoff, and robots.txt honoured by default. There is no inbound
rate limit — put this behind a reverse proxy before exposing it publicly.
