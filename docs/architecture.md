# Architecture

## Where work happens

```
┌───────────────────────── browser ──────────────────────────┐
│  popup                                                     │
│    1. chrome.tabs.query({active, currentWindow})           │
│    2. executeScript(world: MAIN)   -> page globals         │
│    3. executeScript(files: content.js)                     │
│    4. tabs.sendMessage(DETECT, globals)                    │
│         │                                                  │
│  content script (isolated world)                           │
│    runDetection({ doc, url, hostname, pageGlobals })       │
│         │                                                  │
│    DetectionResult ──► popup UI ──► POST /products/track   │
│                    └─► service worker (badge)              │
│                                                            │
│  service worker, every 5 min                               │
│    GET /notifications/undelivered -> chrome.notifications  │
└──────────────────────────┬─────────────────────────────────┘
                           │
┌──────────────────────────▼─────────────────────────────────┐
│  FastAPI          auth · products · history · rules        │
│  PostgreSQL       9 tables, Alembic-migrated               │
│  Redis + Celery   beat every 5 min -> due products         │
│                     group by host -> one task per store    │
│                       fetch -> detect -> compare -> notify │
│  Resend + Discord email and webhook delivery               │
└────────────────────────────────────────────────────────────┘
```

## Decisions worth explaining

### The detection engine exists twice, on purpose

Once in TypeScript (`extension/src/detection/`) and once in Python
(`backend/app/detection/`). They implement the same six layers, the same
priority order, the same three-valued stock vocabulary and the same money
parsing, and they are held to the **same fixtures**.

The alternative — detect only in the browser, or only on the server — is worse
in both directions. The browser sees pages that need a session and pages that
render client-side, which a server fetch cannot reach. The server has to re-read
the page on a schedule, which the browser cannot do while closed. So both need
it, and the cost of that is one invariant: **they must agree**. If they drifted,
the first monitored check after tracking would report a price change that never
happened. That is what the shared fixtures are guarding.

### On-demand injection, not a declared content script

There is **no** `content_scripts` block and **no** host permission for any shop.
The cost is one injection per popup open. What it buys:

- Chrome does not show "read and change all your data on all websites"
- the extension genuinely cannot read a page you did not click on
- nothing runs on any page you are merely browsing

`activeTab` is granted when the user invokes the action, which is exactly the
moment we need it and no earlier.

### Two worlds, one detection run

Content scripts run in an isolated world: they see the DOM but not the page's
own `window`, where `__NEXT_DATA__` lives. So the popup does both — a MAIN-world
function harvests a size-capped, cycle-safe snapshot of the page's state
objects, and the content script receives it in the `DETECT` message. Detection
therefore sees the live DOM *and* the app state in a single pass.

`readPageGlobals` is serialised with `Function.prototype.toString()`, so it is
written to be completely self-contained — no imports, no closure variables. The
build is checked for this.

### The service worker does almost nothing

Badge, plus a five-minute alarm that asks the backend whether anything happened
and raises a native notification for each thing that did. It deliberately does
not monitor: an MV3 worker is evicted after ~30 seconds idle, and a laptop is
the wrong place to poll a thousand shops from.

Alerts are acknowledged only after they actually reach the user, so a browser
that was closed for a day still gets them.

### Adapters invert the usual relationship

The generic pipeline runs first and produces a complete result. An adapter is
then handed that result and may fill gaps.

```ts
interface StoreAdapter {
  id: string;
  canHandle(ctx): boolean;
  detectProduct?(input): Partial<ProductData> | null;
  detectVariants?(input): Variant[] | null;
  detectAvailability?(input): StockStatus | null;
  detectPrice?(input): PriceData | null;
  isProductPage?(ctx): boolean | undefined;
  authoritative?: boolean;   // replace rather than fill — use sparingly
}
```

Returning `null` is the expected answer most of the time. Of the nine adapters,
eight contribute only a brand default and a product-id pattern; only Amazon
carries selectors, because Amazon publishes no structured data at all.

A broken adapter cannot take the pipeline down: `canHandle` and the whole
adapter pass are wrapped.

### Monitoring is built around not lying

```
fetch ──► detect ──► compare ──► persist ──► notify
```

Every stage can fail, and the rule at every stage is that **a failure of ours is
not a fact about the product**:

| Outcome | `CheckStatus` | Effect on stored stock |
|---|---|---|
| 200 with a product | `OK` | updated |
| 200, nothing parseable (bot wall, interstitial) | `PARTIAL` | **unchanged** |
| timeout, connection error, 5xx | `FAILED` | **unchanged** |
| 401 / 403 / 429 | `BLOCKED` | **unchanged**, harsher backoff |
| 404 / 410 | `NOT_FOUND` | **unchanged**, checked daily |

Backoff is exponential per product and capped; a recovery resets the counter.
Requests to one host are serialised behind a process-wide throttle with jitter,
and robots.txt is honoured by default. Celery groups due products **by host** so
one task handles one store in sequence — fanning out per product would defeat
the throttle.

### Change detection vs. notification

Two modules, deliberately separate.

`services/changes.py` decides *what happened*. It never writes `UNKNOWN` over a
known state, and a variant the store has only just started listing is recorded
but is not a change — there is no previous state for it to have changed from.
Variants match on the store's id first and a normalised name second, so a size's
history survives the store rewriting its internal ids.

`notifications/engine.py` decides *what is worth an interruption*. Alerts fire on
transitions, and the `notifications` table is the memory of what has already been
said — memory that survives a restart, which a cache would not. A restock is
suppressed only if the variant has not been recorded out of stock since the last
alert about it, which is what makes `out → in → out → in` two notifications
rather than one.

A price wobble below 1% or one currency unit is not news.

### Rules override heuristics, they do not stack with them

`services/rules.py` is a third decision, layered on top: if a product has active
`watch_rule` rows, `notifications/engine.py` evaluates those and returns,
skipping the built-in heuristics entirely. Running both would mean a user who
asked for "M under ₹10,000" also gets pinged about L at ₹14,000 — an explicit
rule is a statement about what *is not* wanted as much as what is.

The evaluator distinguishes transitions from states. `back_in_stock` reads the
change set, so it can only fire on the check where the crossing happened;
`in_stock` reads the current state and would otherwise fire forever, which is
what `cooldown_minutes` bounds. `UNKNOWN` satisfies no condition in either mode.

Delivery is separate again — `monitoring/engine.py:deliver` fans one alert out
to the channels its rule asked for, and channel failures are recorded on the
notification row rather than raised. A dead Discord webhook must not be able to
abort a monitoring run.

### Money is `Numeric`, never `float`

Prices are `Numeric(12, 2)` in the database and `Decimal` in Python, quantised
to two places before comparison as well as before storage. Without that, a
scraped `1149.000` and a stored `1149.00` compare unequal and every single check
looks like a price change.

## Data model

```
User ──┬── TrackedProduct ──┬── TrackedVariant ── StockHistory
       │        │           └── PriceHistory
       │        └── MonitoringJob
       └── Notification
Store ─────────┘
```

- **PriceHistory** records *every observation*, changed or not — that is what
  makes "7-day low" and "average" meaningful; a series of changes only cannot
  tell you how long a price held.
- **StockHistory** records *transitions only* — the opposite choice for the
  opposite reason: what matters is when a size came back, and a row per check
  would bury it.
- **MonitoringJob** is one audit row per attempt. When a store changes its
  markup, this is how you find out when it started failing and whether it is one
  store or all of them.

`Store` rows are created on demand the first time a product from that host is
tracked, so the table grows to fit what users actually shop on.

## Configuration

Everything environment-driven (`.env.example` documents each key). In production
the app refuses to start with an unsafe configuration — a missing `SECRET_KEY`,
`DEBUG` left on, SQLite, or email enabled without a key — and logs every problem
at once rather than failing on whichever is checked first.
