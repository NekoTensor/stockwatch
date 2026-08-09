"""Shared vocabulary.

These are plain string enums stored as `String` columns rather than native
database enums: adding a notification type should be a code change and a
migration-free deploy, not an `ALTER TYPE`.
"""

from __future__ import annotations

from enum import StrEnum


class StockStatus(StrEnum):
    """Three-valued on purpose.

    `UNKNOWN` is what a failed fetch, an unparseable page or an unrecognised
    widget produces. It is never written over a known state, and it never
    triggers a notification. A tracker that reports "out of stock" because its
    own request failed is worse than useless.
    """

    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class CheckStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"          # fetched, but some fields were unreadable
    FAILED = "failed"            # network/HTTP/parse failure
    BLOCKED = "blocked"          # 403/429/captcha — back off harder
    NOT_FOUND = "not_found"      # 404/410 — the product is gone


class NotificationType(StrEnum):
    STOCK_AVAILABLE = "STOCK_AVAILABLE"
    PRICE_DROP = "PRICE_DROP"
    TARGET_PRICE_REACHED = "TARGET_PRICE_REACHED"
    LOWEST_PRICE_REACHED = "LOWEST_PRICE_REACHED"
    PRICE_INCREASE = "PRICE_INCREASE"
    COMBINED_STOCK_AND_PRICE = "COMBINED_STOCK_AND_PRICE"


class NotificationChannel(StrEnum):
    BROWSER = "browser"
    EMAIL = "email"


class NotificationPriority(StrEnum):
    NORMAL = "normal"
    HIGH = "high"


class VariantType(StrEnum):
    SIZE = "size"
    COLOR = "color"
    SHADE = "shade"
    CAPACITY = "capacity"
    LENGTH = "length"
    FLAVOR = "flavor"
    STYLE = "style"
    GENERIC = "generic"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
