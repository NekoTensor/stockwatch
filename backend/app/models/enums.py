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
    DISCORD = "discord"


class PriceVerdict(StrEnum):
    """The one-word answer to "should I buy this now?".

    `UNKNOWN` is not a hedge, it is the honest answer while the series is too
    short to say anything: a verdict from three observations is a coin toss
    wearing a suit.
    """

    BUY = "buy"
    FAIR = "fair"
    HIGH = "high"
    UNKNOWN = "unknown"


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


class StockCondition(StrEnum):
    """What a watch rule wants the stock to do."""

    ANY = "any"                      # stock is irrelevant to this rule
    BACK_IN_STOCK = "back_in_stock"  # the transition, not the state
    IN_STOCK = "in_stock"            # currently buyable, however it got there
    OUT_OF_STOCK = "out_of_stock"    # tell me when it goes


class PriceCondition(StrEnum):
    """What a watch rule wants the price to do."""

    ANY = "any"                        # price is irrelevant to this rule
    BELOW = "below"                    # <= a number the user chose
    DROPS_BY_PERCENT = "drops_by_percent"   # fell this much versus the last check
    AT_LOWEST = "at_lowest"            # cheapest we have ever recorded
    BELOW_AVERAGE = "below_average"    # this far under the 30-day average


class ConditionCombine(StrEnum):
    """How the two conditions are joined when both are set."""

    ALL = "all"  # both must hold - "my size, at my price"
    ANY = "any"  # either is enough
