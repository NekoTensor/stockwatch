# How detection works

This document is the reference for the part of StockWatch that has to be right:
turning an arbitrary page into a `ProductData`, or honestly admitting it cannot.

> The engine exists twice — `extension/src/detection/` in TypeScript for the
> browser, `backend/app/detection/` in Python for the monitoring workers. Same
> layers, same priority order, same vocabulary, same fixtures. Everything below
> describes both; file paths are given for the TypeScript side.

## The contract

> **The core detection system knows nothing about individual stores.**

`src/detection/` contains no store names, no store hostnames and no store
selectors. Adding a store must mean adding a file under `src/adapters/`, never
editing the pipeline. If a change to support one store would touch
`detection/`, the change is in the wrong place — the fix belongs in a layer,
where every store benefits.

## The pipeline

`src/detection/pipeline.ts`, in order:

1. **Identify the store** from the hostname (`stores/registry.ts`). This only
   produces a *label* and some URL heuristics — detection never depends on it.
2. **Resolve an adapter** (`adapters/registry.ts`). Falls back to `GenericAdapter`.
3. **Run every layer**, each isolated in a `try/catch`. One broken layer must
   never cost us the other five; failures land in `result.warnings`.
4. **Merge** field-by-field by trust (`merge.ts`).
5. **Adapter pass** — fills gaps only, unless the adapter sets `authoritative`.
6. **Normalise** — absolute image URLs, campaign params stripped from the
   product URL, product id recovered from the URL if nothing else supplied one,
   currency fallback, duplicate variants collapsed.
7. **Score and classify** — `detected` / `partial` / `not_a_product`.

## The layers

| Layer | File | Trust |
|-------|------|-------|
| JSON-LD | `layers/jsonld.ts` | 100 |
| Microdata | `layers/microdata.ts` | 85 |
| Embedded JSON | `layers/embedded.ts` | 80 |
| OpenGraph | `layers/opengraph.ts` | 70 |
| DOM heuristics | `layers/dom.ts` | 40 |
| Meta tags | `layers/metatags.ts` | 35 |
| URL | — | 30 |

Two notes on the ordering:

- **Meta tags sit below the DOM.** That layer is mostly `<title>`, which is SEO
  copy ("Buy X Online at Best Price | Store"). A rendered `<h1>` inside the
  product area is a better answer whenever we have one.
- **Trust is per field, not per page.** A page routinely takes its name from
  JSON-LD, its sale price from the DOM and its per-size stock from the rendered
  widget. No single layer would have produced that combination.

### JSON-LD

Handles `@graph`, arrays, `@type` arrays, `ProductGroup`/`hasVariant`, and
`Offer` / `AggregateOffer` / arrays of offers. When several products are on one
page, the node whose `url` matches the page wins.

A product with **several named offers is a variant matrix** — each offer is a
size with its own SKU, price and availability. That is the single richest
variant source on the web. Offer names that are all long SKU strings rather than
short labels are rejected as noise.

### Embedded JSON

Reads inline `<script>` payloads (`__NEXT_DATA__`, `application/json` blocks,
and balanced `window.__X__ = {…}` literals extracted with a string-aware brace
matcher) plus globals harvested from the page's MAIN world.

There are **no per-store paths**. `util/json.ts` walks the object graph — depth
capped, cycle-safe, node-capped — and scores every object:

```
name-ish string                +2
price-ish number               +3
both together                  +2   ← the combination is the real signal
brand / sku / image            +1 each
non-empty variants array       +2
self-identifies as a product   +3
```

Nodes scoring ≥ 5 are candidates; the best three are merged. This is why a
Shopify boutique nobody has heard of works: it ships a `{name, price, sizes}`
object somewhere, whatever it calls the wrapper. It is also why Google Tag
Manager's `dataLayer` works for free.

Prices are read one level deep as well as flat, because
`price: { mrp: 2299, discounted: 1149 }` is at least as common as `price: 1149`.

### MAIN-world harvesting

Content scripts run in an isolated world and **cannot** see
`window.__NEXT_DATA__`. So `content/pageGlobals.ts` is injected into the MAIN
world by the popup via `chrome.scripting.executeScript({ world: 'MAIN', func })`.

Because it is serialised with `Function.prototype.toString()`, that function
must be entirely self-contained — no imports, no closure variables. It snapshots
a list of known globals plus any global whose *name* looks like app state,
under a total character budget, skipping DOM nodes and throwing getters.

### DOM heuristics

Nothing store-specific: it looks for what a shopper looks for.

- **Scope.** Work inside the product-detail subtree when one is identifiable,
  and skip navigation, footers, carts and anything whose class says
  `recommend|related|carousel|cross-sell|recently-viewed`.
- **Price.** Collect elements whose *whole text* is short (≤ 40 chars) and
  contains a currency marker, keep only the innermost matches, then score on
  class/id hints, DOM distance to the heading, and computed font size.
  Struck-through candidates are penalised and become the *original* price.
- **Variants.** Group plausible controls by parent, then keep the group whose
  labels look like sizes/shades or whose container says it is a picker.
  Availability comes from `disabled`, `aria-disabled`, `data-available="false"`,
  disabled-ish class names, a disabled inner `<input>`, `line-through`,
  `pointer-events: none`, or low opacity.
- **Listing detection.** A category page has every individual signal a product
  page has. What differs is *repetition*: three or more sibling elements of the
  same tag, each with its own price and its own link. That costs 30 points.

## Availability

```ts
type StockStatus = 'in_stock' | 'out_of_stock' | 'unknown';
```

`util/availability.ts` is the only place this vocabulary is interpreted.

- schema.org: `InStock`/`OnlineOnly`/`LimitedAvailability`/`PreOrder` → in stock;
  `OutOfStock`/`SoldOut`/`Discontinued`/`BackOrder` → out of stock.
- Text: **out-of-stock phrases are checked first**, because "notify me when
  available" contains the word "available".
- Flags: `0` is out of stock, `undefined` is unknown. `outOfStock: true` is
  handled by inverting.
- **Anything unrecognised returns `unknown`.** This is the invariant the tests
  guard most closely.

`mergeAvailability` resolves a genuine disagreement to `in_stock` — a missed
restock costs the user the item, a spurious ping costs a glance.

## Merging variants

The set with the best combination of size, trust and *known* availability
becomes the skeleton; other sets then fill in availability and SKUs for matching
names, matched on a normalised key so `UK 8` and `uk-8` collapse.

This is exactly the Zara/H&M case: structured data names the sizes, the DOM
knows which buttons are greyed out.

## Confidence

Additive, capped to 0–100. No single signal carries a page; no single missing
signal sinks one.

```
JSON-LD product        +30      title present         +10
microdata product      +18      price present         +18
og:type=product        +18      variants present      +10
embedded product       +14      buy button            +14
                                breadcrumb / gallery  +4 each
URL looks like product +10      adapter says yes      +15
URL looks like listing −25      adapter says no       −30
repeated priced grid   −30
```

| Result | Condition |
|--------|-----------|
| `detected` | a name **and** (a price or variants), score ≥ 55 |
| `partial` | a name, score ≥ 35 |
| `not_a_product` | otherwise |

`partial` is a first-class outcome, not a failure. A page where we found the
product and its price but could not read the size widget is worth tracking for
price alone — and the popup says exactly which fields are missing rather than
quietly showing blanks.

## Testing

`extension/tests/` runs the real pipeline against six fixtures, each a *shape*
of page rather than a copy of one store:

| Fixture | Proves |
|---------|--------|
| `jsonld-apparel.html` | offer-per-size variants; ignores the recommendations rail |
| `og-and-dom.html` | OpenGraph price + DOM-only stock, struck-through MRP |
| `embedded-state.html` | client-rendered page, product only in a JSON blob |
| `microdata.html` | itemprop extraction; nested Review not mistaken for the product |
| `dom-only.html` | unknown store, zero structured data, shade variants |
| `amazon-like.html` | no structured data at all; adapter selectors; camelCase disabled classes |
| `listing-page.html` | a category grid is refused |

Plus a `dataLayer` case built inline, and unit tests for price parsing, store
identification, URL cleaning and the merge rules.

**The same fixtures run against the Python implementation** in
`backend/tests/test_detection.py`, loaded straight out of the extension's test
directory. That is the mechanism that keeps the two engines honest.

## Two bugs worth remembering

Both were found by these tests, and both are the kind that silently degrade
rather than crash:

- **A bare `nav` alternative in the noise-region pattern matched inside the word
  "un-av-ailable"**, so every Amazon swatch with `class="swatchUnavailable"` was
  discarded as navigation. Token boundaries in that pattern are now written as
  "not a letter or digit" rather than `\b`, because `_` is a word character and
  `mini_bag` would otherwise slip through.
- **The price pattern matched a prefix**: `"12990.00"` parsed as `129`, because
  the grouped alternative `\d{1,3}(…)` matched and won before the longer one was
  tried. It is now a single permissive run of digits and separators, with
  `parseAmount` deciding what the separators meant.
