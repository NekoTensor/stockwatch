# Chrome Web Store submission

Everything the listing form asks for, with the answers this extension can
truthfully give. Review takes days rather than hours when an item asks for host
permissions, so the goal here is to give the reviewer no reason to come back
with a question.

Before submitting, read [deploy.md](deploy.md): the backend has to be live at
the https address the build points at, or the reviewer will install the
extension, fail to sign in, and reject it as non-functional.

## Package

```bash
cd extension
STOCKWATCH_API_URL=https://api.yourdomain.com/api npm run build:release
cd dist && zip -r ../stockwatch.zip .
```

Zip the *contents* of `dist/`, not the folder. Check the manifest inside the zip
names your API and your version before uploading — both are generated, and both
are what the reviewer will read.

## Listing

**Name.** StockWatch — Universal Product Tracker

**Summary** (132 characters, and it is the only line most people read):

> Open any product page, click once, and StockWatch already knows the product, price and sizes.

**Category.** Shopping

**Description.** Lead with what it does before how it works:

> StockWatch tells you when the thing you want comes back in your size, or drops
> to a price worth paying.
>
> Open any product page and click the icon. StockWatch reads the page — name,
> brand, price, every size and which of them are actually buyable — and shows
> you what it found. Choose the sizes you care about, and it watches them from
> then on.
>
> **Your size, not the store's stock.** Most trackers tell you a product is
> available when any size is. StockWatch tracks the sizes you picked, so "back
> in stock" means back in yours.
>
> **Knowing when to buy.** Every check records the price, so you get the range
> it has actually sold at rather than the discount the page claims: the lowest
> in 30 days, where today sits in that range, and whether this is a good price
> or just a sale badge.
>
> **Watching continues with the browser closed.** Checks run on the server, not
> in your browser, so nothing depends on leaving a tab open.
>
> **It reads pages only when you ask.** There is no background content script.
> StockWatch looks at a page when you open it on that page, and what it finds
> stays on your device unless you press Track.
>
> Works on Zara, H&M, Uniqlo, Nike, Adidas, Amazon, Myntra, Ajio and Nykaa, and
> on most other shops through structured data that stores already publish.

**Assets.**

| | |
|---|---|
| Icon | 128×128 — `extension/dist/icons/icon128.png` |
| Screenshots | 1280×800, at least one, five is better. `docs/assets/popup.png` and `dashboard.png` are the starting point but need resizing |
| Small promo tile | 440×280, optional but it is what appears in category browsing |

**Privacy policy URL.**
`https://github.com/NekoTensor/stockwatch/blob/main/PRIVACY.md`

## Single purpose

The store requires one purpose, described narrowly. Ours:

> StockWatch tracks the availability and price of products the user explicitly
> chooses, and notifies them when either changes.

Everything in the extension serves that: detection reads the product, the popup
chooses what to watch, the dashboard reviews it, and the service worker delivers
the alerts.

## Permission justifications

Each field takes a sentence or two. These are the true answers, and each names
the feature that stops working without it.

| Permission | Justification |
|---|---|
| `activeTab` | Reads the product page the user is looking at, at the moment they click the extension icon, to extract the product's name, price, image and sizes. This is what replaces a persistent content script: without it StockWatch cannot see the product the user is asking it to track. |
| `scripting` | Injects the detection script into that one tab, on that click, to run the extraction described above. Nothing is injected into any other tab, and nothing is injected until the user opens the popup. |
| `storage` | Stores the sign-in session, the server address, and the user's tracking choices if the server cannot be reached at the moment they press Track. |
| `alarms` | Wakes the service worker every five minutes to collect alerts the backend has raised. An MV3 worker is evicted when idle, so an alarm is the only way to deliver a notification that arrives while the popup is closed. |
| `notifications` | Shows the "back in stock" or "price dropped" alert. This is the product's output; without it the user is never told. |
| Host permission (the API) | The single https origin of the StockWatch backend, which stores tracked products and performs the monitoring. It is the only host the extension contacts. |
| Optional host permissions | Requested at runtime, and only if the user types a different server address into the popup, because StockWatch can be self-hosted. A user who never changes that field is never asked and never grants it. |
| Remote code | None. All JavaScript is bundled in the package; nothing is fetched and evaluated at runtime. |

The reviewer's usual question about a broad pattern is answered by *when* it is
asked for: `https://*/*` is in `optional_host_permissions`, never granted at
install, and requested only by the explicit act of pointing the extension at
your own server.

## Data disclosures

The "Privacy practices" tab. Tick honestly — a mismatch between this and the
policy is a takedown, and it is the single most common one.

| Data type | Collected | Why |
|---|---|---|
| Personally identifiable information | **Yes** — email address | The account that owns the tracked products and receives the alerts |
| Authentication information | **Yes** — password | Sign-in. Hashed with bcrypt on the server, never stored in the extension |
| User activity | **Yes** — the product pages the user chooses to track | The server has to hold the URL to keep checking it |
| Website content | **No** | Page content is read on the device and discarded unless the user tracks that product |
| Location, health, financial, personal communications, web history | **No** | |

Then the three certifications, all of which hold:

- Data is not sold to third parties.
- Data is used only for the single purpose above.
- Data is not used to determine creditworthiness or for lending.

## Notes for the reviewer

Put this in the "Notes to reviewer" box. It is the difference between a review
and a rejection, because the extension does nothing visible until it is signed
in:

> StockWatch requires an account, because monitoring runs on our server rather
> than in the browser. A test account is below.
>
> Email: reviewer@yourdomain.com
> Password: [set one before submitting]
>
> To see it work: sign in, open any product page (for example a Zara or H&M
> product), click the StockWatch icon, and the popup will show the detected
> product with its sizes. Press "Track product", then open the dashboard from
> the extension's options to see it listed with its price history.
>
> The extension reads a page only when the icon is clicked, using activeTab.
> There is no content script registered in the manifest.

Create that account on the production backend and confirm it works before
submitting. Do not reuse a personal account.

## After the first submission

- Version numbers only go up, and a version already uploaded cannot be reused.
  Bump `extension/package.json`; the build writes it into the manifest.
- A change to the permission list re-triggers full review — including adding a
  host permission, which is what happens if the API moves to a new domain.
- Rejections name a policy section. Read that section rather than guessing at
  the reason, and reply in the same thread rather than resubmitting silently.
