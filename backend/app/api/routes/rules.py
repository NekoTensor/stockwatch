from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import TrackedProduct, TrackedVariant, WatchRule
from app.schemas.watch_rule import WatchRuleCreate, WatchRuleOut, WatchRuleUpdate

router = APIRouter(prefix="/products/{product_id}/rules", tags=["watch rules"])


def _to_out(rule: WatchRule) -> WatchRuleOut:
    out = WatchRuleOut.model_validate(rule)
    out.description = rule.describe()
    out.variant_name = rule.variant.variant_name if rule.variant else None
    return out


def _require_product(db, user, product_id: int) -> TrackedProduct:  # noqa: ANN001
    product = db.scalars(
        select(TrackedProduct).where(TrackedProduct.id == product_id, TrackedProduct.user_id == user.id)
    ).first()
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.")
    return product


def _resolve_variant(product: TrackedProduct, variant_id: str | None) -> TrackedVariant | None:
    """Map the store's variant label onto our row, rejecting unknown ones.

    Silently ignoring a bad id would create a rule that watches every size while
    the user believes it watches one.
    """
    if variant_id is None:
        return None
    for variant in product.variants:
        if variant.variant_id == variant_id:
            return variant
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"No variant {variant_id!r} on this product.")


@router.get("", response_model=list[WatchRuleOut])
def list_rules(product_id: int, user: CurrentUser, db: DbSession) -> list[WatchRuleOut]:
    product = _require_product(db, user, product_id)
    rules = db.scalars(
        select(WatchRule).where(WatchRule.tracked_product_id == product.id).order_by(WatchRule.id)
    ).unique()
    return [_to_out(rule) for rule in rules]


@router.post("", response_model=WatchRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(product_id: int, payload: WatchRuleCreate, user: CurrentUser, db: DbSession) -> WatchRuleOut:
    product = _require_product(db, user, product_id)
    variant = _resolve_variant(product, payload.variant_id)

    rule = WatchRule(
        user_id=user.id,
        tracked_product_id=product.id,
        tracked_variant_id=variant.id if variant else None,
        label=payload.label,
        stock_condition=payload.stock_condition.value,
        price_condition=payload.price_condition.value,
        combine=payload.combine.value,
        price_value=payload.price_value,
        percent_value=payload.percent_value,
        notify_browser=payload.notify_browser,
        notify_email=payload.notify_email,
        notify_discord=payload.notify_discord,
        is_active=payload.is_active,
        cooldown_minutes=payload.cooldown_minutes,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.patch("/{rule_id}", response_model=WatchRuleOut)
def update_rule(
    product_id: int, rule_id: int, payload: WatchRuleUpdate, user: CurrentUser, db: DbSession
) -> WatchRuleOut:
    product = _require_product(db, user, product_id)
    rule = db.scalars(
        select(WatchRule).where(WatchRule.id == rule_id, WatchRule.tracked_product_id == product.id)
    ).first()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")

    data = payload.model_dump(exclude_unset=True)

    if "variant_id" in data:
        variant = _resolve_variant(product, data.pop("variant_id"))
        rule.tracked_variant_id = variant.id if variant else None

    for field, value in data.items():
        setattr(rule, field, value.value if hasattr(value, "value") else value)

    # Re-validate the merged result, so a patch cannot leave a rule in a state
    # the create endpoint would have rejected.
    WatchRuleCreate(
        label=rule.label,
        stock_condition=rule.stock_condition,
        price_condition=rule.price_condition,
        combine=rule.combine,
        price_value=rule.price_value,
        percent_value=rule.percent_value,
        notify_browser=rule.notify_browser,
        notify_email=rule.notify_email,
        notify_discord=rule.notify_discord,
        is_active=rule.is_active,
        cooldown_minutes=rule.cooldown_minutes,
    )

    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_rule(product_id: int, rule_id: int, user: CurrentUser, db: DbSession) -> Response:
    product = _require_product(db, user, product_id)
    rule = db.scalars(
        select(WatchRule).where(WatchRule.id == rule_id, WatchRule.tracked_product_id == product.id)
    ).first()
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found.")

    db.delete(rule)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
