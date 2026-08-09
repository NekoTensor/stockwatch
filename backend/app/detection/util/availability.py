"""Turning a store's idea of "can I buy this" into a `StockStatus`.

The governing rule, identical to the extension's: **absence of evidence is not
evidence of absence.** Anything not positively recognised returns ``UNKNOWN``.
"""

from __future__ import annotations

import re

from app.models.enums import StockStatus

_SCHEMA_IN = re.compile(r"(InStock|OnlineOnly|InStoreOnly|LimitedAvailability|PreOrder|PreSale)$", re.I)
_SCHEMA_OUT = re.compile(r"(OutOfStock|SoldOut|Discontinued|BackOrder)$", re.I)

#: Checked before the "in stock" phrases: "notify me when available" contains
#: the word "available".
_OUT_TEXT = re.compile(
    r"\b(out of stock|sold out|currently unavailable|temporarily unavailable|not available|"
    r"unavailable|notify me|email me when|coming soon|agotado|epuise|ausverkauft|esgotado)\b",
    re.I,
)
_IN_TEXT = re.compile(
    r"\b(in stock|add to (cart|bag|basket)|buy (it )?now|available now|ready to ship|"
    r"en stock|disponible|auf lager)\b",
    re.I,
)

_TRUE_TOKENS = {"true", "yes", "y", "1", "available", "instock", "in_stock"}
_FALSE_TOKENS = {"false", "no", "n", "0", "unavailable", "outofstock", "out_of_stock"}


def from_schema(value: object) -> StockStatus:
    if not isinstance(value, str) or not value.strip():
        return StockStatus.UNKNOWN
    token = value.strip()
    if _SCHEMA_OUT.search(token):
        return StockStatus.OUT_OF_STOCK
    if _SCHEMA_IN.search(token):
        return StockStatus.IN_STOCK
    return from_text(token)


def from_text(text: str | None) -> StockStatus:
    if not text:
        return StockStatus.UNKNOWN
    if _OUT_TEXT.search(text):
        return StockStatus.OUT_OF_STOCK
    if _IN_TEXT.search(text):
        return StockStatus.IN_STOCK
    return StockStatus.UNKNOWN


def from_flag(value: object) -> StockStatus:
    """Booleans, counts and string flags. ``0`` is sold out; ``None`` is unknown."""
    if value is None:
        return StockStatus.UNKNOWN
    if isinstance(value, bool):
        return StockStatus.IN_STOCK if value else StockStatus.OUT_OF_STOCK
    if isinstance(value, (int, float)):
        return StockStatus.IN_STOCK if value > 0 else StockStatus.OUT_OF_STOCK
    if isinstance(value, str):
        token = value.strip().lower()
        if not token:
            return StockStatus.UNKNOWN
        if token in _TRUE_TOKENS:
            return StockStatus.IN_STOCK
        if token in _FALSE_TOKENS:
            return StockStatus.OUT_OF_STOCK
        return from_schema(token)
    return StockStatus.UNKNOWN


def from_negative_flag(value: object) -> StockStatus:
    """For fields phrased negatively, e.g. ``outOfStock: true``."""
    positive = from_flag(value)
    if positive is StockStatus.IN_STOCK:
        return StockStatus.OUT_OF_STOCK
    if positive is StockStatus.OUT_OF_STOCK:
        return StockStatus.IN_STOCK
    return StockStatus.UNKNOWN


def merge(a: StockStatus, b: StockStatus) -> StockStatus:
    """Combine two layers' opinions.

    A confident answer beats ``UNKNOWN``; a genuine disagreement resolves to
    ``IN_STOCK``, because a missed restock costs the user the item while a
    spurious ping costs them a glance.
    """
    if a == b:
        return a
    if a is StockStatus.UNKNOWN:
        return b
    if b is StockStatus.UNKNOWN:
        return a
    return StockStatus.IN_STOCK
