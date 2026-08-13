from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ConditionCombine, PriceCondition, StockCondition
from app.schemas.common import ORMModel


class WatchRuleBase(BaseModel):
    label: str | None = Field(default=None, max_length=160)
    #: The store's own id for the variant ("M", "UK 9"), not our row id - the
    #: client already has those from the product payload.
    variant_id: str | None = Field(default=None, max_length=191)

    stock_condition: StockCondition = StockCondition.ANY
    price_condition: PriceCondition = PriceCondition.ANY
    combine: ConditionCombine = ConditionCombine.ALL

    price_value: Decimal | None = None
    percent_value: Decimal | None = None

    notify_browser: bool = True
    notify_email: bool = True
    notify_discord: bool = False

    is_active: bool = True
    cooldown_minutes: int = Field(default=720, ge=0, le=60 * 24 * 30)

    @model_validator(mode="after")
    def _conditions_are_answerable(self) -> WatchRuleBase:
        """Reject rules that cannot fire, or that would fire forever.

        Catching these here means the evaluator never has to defend against a
        threshold that was never supplied.
        """
        if self.stock_condition is StockCondition.ANY and self.price_condition is PriceCondition.ANY:
            raise ValueError("A rule needs at least one condition on stock or price.")

        if self.price_condition is PriceCondition.BELOW and self.price_value is None:
            raise ValueError("A 'below' rule needs a price to stay below.")

        if (
            self.price_condition in {PriceCondition.DROPS_BY_PERCENT, PriceCondition.BELOW_AVERAGE}
            and self.percent_value is None
        ):
            raise ValueError("A percentage rule needs a percentage.")

        if self.price_value is not None and self.price_value <= 0:
            raise ValueError("The price must be greater than zero.")

        if self.percent_value is not None and not (0 < self.percent_value <= 100):
            raise ValueError("The percentage must be between 0 and 100.")

        if not (self.notify_browser or self.notify_email or self.notify_discord):
            raise ValueError("A rule needs at least one notification channel.")

        return self


class WatchRuleCreate(WatchRuleBase):
    pass


class WatchRuleUpdate(BaseModel):
    """Every field optional; validated as a whole once merged onto the row."""

    label: str | None = Field(default=None, max_length=160)
    variant_id: str | None = Field(default=None, max_length=191)
    stock_condition: StockCondition | None = None
    price_condition: PriceCondition | None = None
    combine: ConditionCombine | None = None
    price_value: Decimal | None = None
    percent_value: Decimal | None = None
    notify_browser: bool | None = None
    notify_email: bool | None = None
    notify_discord: bool | None = None
    is_active: bool | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)


class WatchRuleOut(ORMModel):
    id: int
    tracked_product_id: int
    tracked_variant_id: int | None
    label: str | None
    description: str = ""

    stock_condition: StockCondition
    price_condition: PriceCondition
    combine: ConditionCombine
    price_value: Decimal | None
    percent_value: Decimal | None

    notify_browser: bool
    notify_email: bool
    notify_discord: bool

    is_active: bool
    cooldown_minutes: int
    last_triggered_at: datetime | None
    trigger_count: int
    created_at: datetime

    #: The store's label for the variant, so the client can render the rule
    #: without joining back to the product.
    variant_name: str | None = None
