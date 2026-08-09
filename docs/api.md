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
| `POST` | `/auth/register` | 10-char minimum, must mix letters with numbers or symbols |
| `POST` | `/auth/login` | Same response for a wrong password and an unknown address, so the endpoint cannot enumerate accounts |
| `POST` | `/auth/refresh` | Returns a new pair |
| `GET` | `/auth/me` | |
| `PATCH` | `/auth/me` | Display name, channel preferences |

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
