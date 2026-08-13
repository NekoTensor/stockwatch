"""Email markup.

Deliberately plain HTML with inline styles and a table-based shell: email
clients are twenty years behind browsers, and a flexbox layout that looks
perfect in a browser preview collapses in Outlook. The visual language matches
the extension - white, black, wide letter-spacing, no rounded corners.
"""

from __future__ import annotations

from decimal import Decimal
from html import escape

from app.models import Notification, TrackedProduct

_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "AED": "AED ", "SGD": "S$"}


def format_price(amount: Decimal | None, currency: str | None) -> str:
    if amount is None:
        return "-"
    symbol = _SYMBOLS.get((currency or "").upper(), "")
    whole = amount.quantize(Decimal("1")) if amount == amount.to_integral_value() else amount
    return f"{symbol}{whole:,}" if symbol else f"{whole:,} {currency or ''}".strip()


def subject_for(notification: Notification) -> str:
    """Lead with the product, not the category of event.

    An inbox shows perhaps sixty characters. "Your size is back in stock" is
    true of every restock alert ever sent and tells the reader nothing about
    *which* thing came back; the product name and size do.
    """
    product = notification.product
    name = product.name or "Your product"
    size = notification.variant.variant_name if notification.variant else None
    price = format_price(notification.price or product.current_price, product.currency)

    if notification.type in {"STOCK_AVAILABLE", "COMBINED_STOCK_AND_PRICE"}:
        if size:
            return f"{name} — size {size} is back at {price}"
        return f"{name} is back in stock at {price}"

    if notification.type == "TARGET_PRICE_REACHED":
        return f"{name} hit your target — now {price}"
    if notification.type == "LOWEST_PRICE_REACHED":
        return f"{name} is at its lowest yet — {price}"
    if notification.type == "PRICE_DROP":
        return f"{name} dropped to {price}"
    if notification.type == "PRICE_INCREASE":
        return f"{name} went up to {price}"

    return f"StockWatch — {name}"


def render_email(
    notification: Notification,
    product: TrackedProduct,
    price_context: str = "",
) -> tuple[str, str]:
    """Return ``(html, plain_text)``.

    Both are produced: a text part is not optional if you want to stay out of
    spam folders, and some clients genuinely prefer it.

    `price_context` is the line that makes this actionable - "12% below the
    30-day average" - and is passed in rather than computed here so the
    template stays free of database access.
    """
    name = escape(product.name or "Your product")
    store = escape(product.store.name if product.store else "")
    variant = escape(notification.variant.variant_name) if notification.variant else ""
    price = format_price(notification.price or product.current_price, product.currency)
    previous = format_price(notification.previous_price, product.currency) if notification.previous_price else ""
    url = escape(product.url, quote=True)
    image = escape(product.image_url, quote=True) if product.image_url else ""

    detail_rows = ""
    if store:
        detail_rows += _row("Store", store)
    if variant:
        detail_rows += _row("Size", variant)
    detail_rows += _row("Price", f"<strong>{price}</strong>" + (f' <span style="color:#8a8a8a;text-decoration:line-through;margin-left:6px">{previous}</span>' if previous else ""))

    # The single line that turns "it's available" into "and it's a good price".
    context_block = (
        f'<tr><td style="padding-bottom:28px;font-size:13px;line-height:1.6;color:#1c7c3c">'
        f"{escape(price_context)}</td></tr>"
        if price_context
        else ""
    )

    image_block = (
        f'<td width="180" valign="top" style="padding:0 24px 0 0">'
        f'<img src="{image}" width="180" alt="{name}" style="display:block;width:180px;height:auto;border:0" />'
        f"</td>"
        if image
        else ""
    )

    html = f"""<!doctype html>
<html>
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" /></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:Helvetica,Arial,sans-serif;color:#000000">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff">
    <tr><td align="center" style="padding:40px 20px">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="width:560px;max-width:100%">
        <tr><td style="padding-bottom:32px;font-size:11px;letter-spacing:.22em;text-transform:uppercase">STOCKWATCH</td></tr>
        <tr><td style="padding-bottom:28px;font-size:22px;line-height:1.3;font-weight:400">{escape(notification.title)}</td></tr>
        <tr><td style="padding-bottom:28px">
          <table role="presentation" cellpadding="0" cellspacing="0" width="100%"><tr>
            {image_block}
            <td valign="top">
              <div style="font-size:15px;line-height:1.45;padding-bottom:16px">{name}</div>
              <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="font-size:12px">{detail_rows}</table>
            </td>
          </tr></table>
        </td></tr>
        <tr><td style="padding-bottom:20px;font-size:13px;line-height:1.6;color:#333333">{escape(notification.message)}</td></tr>
        {context_block}
        <tr><td style="padding-bottom:36px">
          <a href="{url}" style="display:inline-block;background:#000000;color:#ffffff;text-decoration:none;padding:14px 32px;font-size:11px;letter-spacing:.18em;text-transform:uppercase">Buy now</a>
        </td></tr>
        <tr><td style="border-top:1px solid #e5e5e5;padding-top:20px;font-size:11px;line-height:1.7;color:#8a8a8a">
          You are receiving this because you asked StockWatch to watch this product.<br />
          Stock and prices are read from the retailer's own page and can change at any time.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text_lines = [
        notification.title,
        "",
        product.name or "",
        f"Store: {product.store.name}" if product.store else "",
        f"Size: {notification.variant.variant_name}" if notification.variant else "",
        f"Price: {price}" + (f" (was {previous})" if previous else ""),
        "",
        notification.message,
        price_context,
        "",
        f"Buy now: {product.url}",
    ]
    text = "\n".join(line for line in text_lines if line)

    return html, text


def _row(label: str, value: str) -> str:
    return (
        f'<tr><td style="padding:3px 0;color:#8a8a8a;width:80px;'
        f'text-transform:uppercase;letter-spacing:.12em;font-size:10px">{label}</td>'
        f'<td style="padding:3px 0">{value}</td></tr>'
    )
