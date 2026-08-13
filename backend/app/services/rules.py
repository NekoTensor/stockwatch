"""Watch rule evaluation.

The monitor used to run a fixed script: if the price moved, consider a price
alert; if a watched size came back, consider a stock alert. This turns that into
a condition evaluator, so "size 9, back in stock" and "any size, under 8,000"
and "my size AND under 4,000" are all the same machinery with different rows.

Two properties are load-bearing and both are about not crying wolf:

* **Transitions, not states.** A rule phrased as a state ("price is under
  8,000") is true on every check once it is true at all. Those rules are gated
  by a cooldown; rules phrased as transitions ("came back in stock") are not,
  because the transition already happened only once.

* **Unknown is never a trigger.** A size we could not read is not a size that
  came back, and a check that failed is not a price drop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.models import TrackedProduct, TrackedVariant, WatchRule
from app.models.enums import ConditionCombine, PriceCondition, StockCondition, StockStatus
from app.services.changes import ChangeSet
from app.services.price_stats import compute_stats

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RuleMatch:
    """A rule that fired, and why - the reason goes into the alert text."""

    rule: WatchRule
    variant: TrackedVariant | None
    reason: str
    stock_met: bool
    price_met: bool

    @property
    def is_restock(self) -> bool:
        return self.stock_met and self.variant is not None


def _variants_in_scope(rule: WatchRule, product: TrackedProduct) -> list[TrackedVariant]:
    """A rule targets one variant, or every variant the user watches."""
    if rule.tracked_variant_id is not None:
        return [v for v in product.variants if v.id == rule.tracked_variant_id]
    watched = [v for v in product.variants if v.is_watched]
    return watched or list(product.variants)


def _evaluate_stock(
    rule: WatchRule, product: TrackedProduct, changes: ChangeSet
) -> tuple[bool, TrackedVariant | None, str]:
    condition = StockCondition(rule.stock_condition)
    if condition is StockCondition.ANY:
        return True, None, ""

    scope = _variants_in_scope(rule, product)
    scope_ids = {v.id for v in scope}

    if condition is StockCondition.BACK_IN_STOCK:
        # A transition, so it can only be satisfied by something that changed
        # during *this* check.
        for change in changes.restocked_variants:
            if change.variant.id in scope_ids:
                return True, change.variant, f"{change.variant.variant_name} is back in stock"
        # No variants at all: fall back to the product flipping to in stock.
        if not product.variants and product.availability == StockStatus.IN_STOCK:
            return True, None, "Back in stock"
        return False, None, ""

    if condition is StockCondition.IN_STOCK:
        for variant in scope:
            if variant.current_stock == StockStatus.IN_STOCK:
                return True, variant, f"{variant.variant_name} is in stock"
        if not product.variants and product.availability == StockStatus.IN_STOCK:
            return True, None, "In stock"
        return False, None, ""

    if condition is StockCondition.OUT_OF_STOCK:
        for change in changes.variant_changes:
            if change.went_out_of_stock and change.variant.id in scope_ids:
                return True, change.variant, f"{change.variant.variant_name} has sold out"
        return False, None, ""

    return False, None, ""


def _evaluate_price(
    db: Session, rule: WatchRule, product: TrackedProduct, changes: ChangeSet
) -> tuple[bool, str]:
    condition = PriceCondition(rule.price_condition)
    if condition is PriceCondition.ANY:
        return True, ""

    current = product.current_price
    if current is None:
        return False, ""

    if condition is PriceCondition.BELOW:
        if rule.price_value is not None and current <= rule.price_value:
            return True, f"price is {current:.0f}, at or below your {rule.price_value:.0f}"
        return False, ""

    if condition is PriceCondition.DROPS_BY_PERCENT:
        # A transition: measured against the previous observation, so it is only
        # true on the check where the drop happened.
        if not changes.price_dropped or changes.previous_price is None or rule.percent_value is None:
            return False, ""
        drop = (changes.previous_price - current) / changes.previous_price * Decimal(100)
        if drop >= rule.percent_value:
            return True, f"price dropped {drop:.0f}%, from {changes.previous_price:.0f} to {current:.0f}"
        return False, ""

    if condition is PriceCondition.AT_LOWEST:
        if product.lowest_price is not None and current <= product.lowest_price:
            return True, f"price is at its lowest recorded, {current:.0f}"
        return False, ""

    if condition is PriceCondition.BELOW_AVERAGE:
        if rule.percent_value is None:
            return False, ""
        stats = compute_stats(db, product)
        if stats.average_30d and stats.average_30d > 0:
            below = (stats.average_30d - current) / stats.average_30d * Decimal(100)
            if below >= rule.percent_value:
                return True, f"price is {below:.0f}% below the 30-day average"
        return False, ""

    return False, ""


def _in_cooldown(rule: WatchRule) -> bool:
    if rule.last_triggered_at is None or rule.cooldown_minutes <= 0:
        return False
    return utcnow() - rule.last_triggered_at < timedelta(minutes=rule.cooldown_minutes)


def _is_state_rule(rule: WatchRule) -> bool:
    """Would this rule stay true on every subsequent check?

    Transitions describe an event that happened once; states describe a
    condition that persists. Only the latter needs a cooldown to stay quiet.
    """
    stock_is_state = StockCondition(rule.stock_condition) in {
        StockCondition.IN_STOCK,
        StockCondition.ANY,
    }
    price_is_state = PriceCondition(rule.price_condition) in {
        PriceCondition.BELOW,
        PriceCondition.AT_LOWEST,
        PriceCondition.BELOW_AVERAGE,
        PriceCondition.ANY,
    }
    return stock_is_state and price_is_state


def evaluate_rules(db: Session, product: TrackedProduct, changes: ChangeSet) -> list[RuleMatch]:
    """Every active rule on this product that is satisfied right now."""
    matches: list[RuleMatch] = []

    for rule in product.watch_rules:
        if not rule.is_active:
            continue

        try:
            stock_met, variant, stock_reason = _evaluate_stock(rule, product, changes)
            price_met, price_reason = _evaluate_price(db, rule, product, changes)
        except Exception:  # noqa: BLE001 - one bad rule must not stop the others
            logger.exception("Rule %s failed to evaluate", rule.id)
            continue

        combine = ConditionCombine(rule.combine)
        satisfied = (stock_met and price_met) if combine is ConditionCombine.ALL else (stock_met or price_met)
        if not satisfied:
            continue

        # A rule where neither side asks for anything would fire on every check
        # forever; that is a misconfiguration, not an alert.
        if (
            StockCondition(rule.stock_condition) is StockCondition.ANY
            and PriceCondition(rule.price_condition) is PriceCondition.ANY
        ):
            continue

        if _is_state_rule(rule) and _in_cooldown(rule):
            continue

        reasons = [text for text in (stock_reason, price_reason) if text]
        matches.append(
            RuleMatch(
                rule=rule,
                variant=variant,
                reason=" and ".join(reasons) if reasons else rule.describe(),
                stock_met=stock_met,
                price_met=price_met,
            )
        )

    return matches


def mark_triggered(rule: WatchRule) -> None:
    rule.last_triggered_at = utcnow()
    rule.trigger_count += 1
