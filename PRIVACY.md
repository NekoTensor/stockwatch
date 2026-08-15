# StockWatch Privacy Policy

**Last updated: 16 August 2026**

StockWatch is a browser extension that watches product pages you choose and
tells you when the price or the stock changes. This policy describes what it
collects, why, and what you can do about it. It is written against what the code
does; if the two ever disagree, the code is the bug.

The operator of the hosted service is the party you accepted this policy from.
If you run your own copy of StockWatch, you are that operator, and no data
described here reaches anyone else.

## The short version

- Pages you visit are read **only when you open the StockWatch popup**, and what
  it finds stays on your device unless you press **Track product**.
- Tracking a product sends **that product's public details** to the server —
  its address, name, price and sizes — so the server can keep checking it while
  your browser is closed.
- There is **no advertising, no analytics, no tracking pixel, and no third-party
  SDK** in the extension. Nothing is sold, and nothing is shared for marketing.
- You can **delete your account and everything attached to it** at any time.

## What is collected

### On your device only

Held in the extension's local storage and never sent anywhere:

| | |
|---|---|
| Session tokens | Prove you are signed in. Cleared when you sign out |
| Your email address | Shown in the popup so you know which account you are in |
| The server address | Which backend this copy talks to |
| Theme preference | Light or dark |
| Unsent tracking drafts | If the server is unreachable when you press Track, your choice is kept so it is not lost, and sent when the server returns |

### Sent to the server when you create an account

Your email address, and a password which is hashed with bcrypt before it is
stored. The plain password is never written down, and cannot be recovered from
what is stored — only checked against.

### Sent to the server when you track a product

The public details of that one product, read from the page you were looking at:
its address, name, brand, category, image, store, currency, current and original
price, whether it is in stock, and the list of sizes or variants with their
availability. Also which of them you asked to be told about, and any target
price or alert rules you set.

### Created by the server as it works

Each check writes what it saw: the price at that moment and any change in
availability. That history is the product — it is what "lowest in 30 days" and
"this is a good price" are computed from.

### Not collected

- **Your browsing history.** The extension has no persistent content script and
  no permission to read pages in the background. It reads a page when you open
  the popup on it, using `activeTab`, and the result stays on your device unless
  you track it.
- **Anything from a page you did not track.** Opening the popup and closing it
  again sends nothing.
- **Payment details.** The hosted service does not take payments at this time.
- **Analytics of any kind.** No usage events, no crash telemetry, no identifiers
  beyond the account you created.

## How it is used

Only to run the service you asked for: to check the products you track, to
decide whether something changed enough to be worth telling you about, and to
send you that alert. Your data is not used to train anything, is not sold, and
is not shared with advertisers.

## Who else sees it

| Recipient | What reaches them | When |
|---|---|---|
| The retailer whose page you track | A request from the **server's** address for that product page. Your address and identity are not sent | On every scheduled check |
| Resend (email delivery) | Your email address and the contents of the alert | Only when an alert is sent by email |
| Discord | The contents of the alert, posted to the channel your webhook names | Only if you configured a Discord webhook |
| Hosting and database providers | The data above, at rest, as infrastructure for the operator | Continuously |

That is the whole list. There is no fifth party.

## Retention and deletion

- **Untrack a product** and its history goes with it.
- **Delete your account** and everything goes: your products, their price and
  stock history, your rules, and your notifications, removed by cascade in the
  same transaction. It is immediate, and there is no soft-delete copy left
  behind. Access tokens issued before deletion are signed rather than stored, so
  they are not individually revoked — but they name an account that no longer
  exists, so the next request made with one fails.

The endpoint is `DELETE /api/auth/me`, which is what the extension calls.

## Security

Passwords are hashed with bcrypt. Sessions use short-lived access tokens with
separately-signed refresh tokens. The hosted service is served over https only.
Sign-in and account creation are rate limited. No secret — no database
credential, no API key — is ever shipped inside the extension: it holds a
session and nothing else, so a compromised copy of the extension leaks one
login, not the service.

No system is perfect, and this one is a small project rather than a bank. Use a
password you do not use elsewhere.

## Children

StockWatch is not directed at children under 13, and accounts are not knowingly
created for them.

## Your rights

You can see everything held about you through the dashboard and the API, correct
your account details, and delete everything at once. If you are in a
jurisdiction that grants you further rights over your data — access, portability,
objection — exercising them is the same action: the delete endpoint above, or a
message to the contact below.

## Changes

Material changes will be reflected here with a new date at the top, and in the
Web Store listing. The version history of this file is public in the repository,
so what changed and when is always checkable.

## Contact

Open an issue at <https://github.com/NekoTensor/stockwatch/issues>, or write to
the address published in the Chrome Web Store listing.
