"""Tracking, updating and querying products."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.base import utcnow
from app.detection.stores import identify_store
from app.detection.urls import clean_url, normalise_hostname
from app.models import (
    Notification,
    PriceHistory,
    StockHistory,
    Store,
    TrackedProduct,
    TrackedVariant,
    User,
)
from app.models.enums import NotificationType, StockStatus
from app.schemas.product import OverviewOut, ProductUpdate, TrackRequest

SORTABLE = {
    "recent": TrackedProduct.created_at.desc(),
    "updated": TrackedProduct.updated_at.desc(),
    "price_drop": TrackedProduct.current_price.asc(),
    "lowest_price": TrackedProduct.current_price.asc(),
    "name": TrackedProduct.name.asc(),
}


def get_or_create_store(db: Session, url: str, name: str | None, slug: str | None) -> Store:
    """One row per domain, created the first time we see it."""
    hostname = normalise_hostname(url)
    identity = identify_store(hostname)

    store = db.scalars(select(Store).where(Store.domain == hostname)).first()
    if store is not None:
        return store

    store = Store(
        slug=slug or identity.slug,
        name=name or identity.name,
        domain=hostname,
        default_currency=identity.currency,
    )
    db.add(store)
    db.flush()
    return store


def track_product(db: Session, user: User, payload: TrackRequest) -> TrackedProduct:
    """Create or update the user's tracking for one product.

    Re-tracking the same URL updates rather than duplicating, which is what
    keeps price history continuous when someone clicks "Track" twice.
    """
    url = clean_url(str(payload.url))
    store = get_or_create_store(db, url, payload.store, payload.store_slug)

    product = db.scalars(
        select(TrackedProduct)
        .where(TrackedProduct.user_id == user.id, TrackedProduct.url == url)
        .options(selectinload(TrackedProduct.variants))
    ).first()

    is_new = product is None
    if product is None:
        product = TrackedProduct(user_id=user.id, url=url)
        db.add(product)

    product.store_id = store.id
    product.name = payload.name
    product.brand = payload.brand or product.brand
    product.category = payload.category or product.category
    product.image_url = payload.image_url or product.image_url
    product.product_id = payload.product_id or product.product_id
    product.sku = payload.sku or product.sku
    product.currency = payload.currency or product.currency or store.default_currency

    product.price_tracking_enabled = payload.price_tracking_enabled
    product.stock_tracking_enabled = payload.stock_tracking_enabled
    product.target_price = payload.target_price
    product.notify_email = payload.notify_email
    product.notify_browser = payload.notify_browser
    product.tracking_enabled = True

    if payload.original_price is not None:
        product.original_price = payload.original_price
    if payload.availability is not StockStatus.UNKNOWN:
        product.availability = payload.availability

    db.flush()

    # The snapshot the extension captured is the first price observation, so the
    # history starts at the moment the user actually saw the price.
    if payload.current_price is not None:
        product.current_price = payload.current_price
        db.add(
            PriceHistory(
                tracked_product_id=product.id,
                price=payload.current_price,
                currency=product.currency,
            )
        )
        if is_new or product.lowest_price is None:
            product.lowest_price = payload.current_price
            product.highest_price = payload.current_price
            product.average_price = payload.current_price
        else:
            product.lowest_price = min(product.lowest_price, payload.current_price)
            product.highest_price = max(product.highest_price or payload.current_price, payload.current_price)

    _sync_variants(db, product, payload)

    # Check it promptly, but not instantly: the extension just read the page, so
    # an immediate re-fetch would only add load.
    product.next_check_at = utcnow() + timedelta(minutes=5)
    db.flush()
    return product


def _sync_variants(db: Session, product: TrackedProduct, payload: TrackRequest) -> None:
    watched = set(payload.watched_variant_ids)
    existing = {variant.variant_id: variant for variant in product.variants}

    for position, incoming in enumerate(payload.variants):
        variant = existing.get(incoming.id)
        if variant is None:
            variant = TrackedVariant(
                tracked_product_id=product.id,
                variant_id=incoming.id,
                variant_name=incoming.name,
                variant_type=incoming.type.value,
                sku=incoming.sku,
                price=incoming.price,
                position=position,
                current_stock=incoming.availability.value,
                previous_stock=StockStatus.UNKNOWN.value,
            )
            if incoming.availability is StockStatus.IN_STOCK:
                variant.last_in_stock_at = utcnow()
            product.variants.append(variant)
            db.add(variant)
        else:
            variant.variant_name = incoming.name
            variant.variant_type = incoming.type.value
            variant.position = position
            if incoming.sku:
                variant.sku = incoming.sku
            if incoming.price is not None:
                variant.price = incoming.price
            # Never write UNKNOWN over a state we already established.
            if incoming.availability is not StockStatus.UNKNOWN:
                variant.current_stock = incoming.availability.value

        # An empty watch list means "the product as a whole", which is correct
        # for something with no variants; otherwise watch exactly what was asked.
        variant.is_watched = incoming.id in watched if watched else not payload.variants


def list_products(
    db: Session,
    user: User,
    *,
    status: str | None = None,
    store_slug: str | None = None,
    search: str | None = None,
    sort: str = "recent",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TrackedProduct], int]:
    query: Select = select(TrackedProduct).where(TrackedProduct.user_id == user.id)

    if status == "in_stock":
        query = query.where(TrackedProduct.availability == StockStatus.IN_STOCK.value)
    elif status == "out_of_stock":
        query = query.where(TrackedProduct.availability == StockStatus.OUT_OF_STOCK.value)
    elif status == "unknown":
        query = query.where(TrackedProduct.availability == StockStatus.UNKNOWN.value)
    elif status == "price_drop":
        query = query.where(
            and_(
                TrackedProduct.original_price.isnot(None),
                TrackedProduct.current_price.isnot(None),
                TrackedProduct.current_price < TrackedProduct.original_price,
            )
        )
    elif status == "lowest_price":
        query = query.where(
            and_(
                TrackedProduct.current_price.isnot(None),
                TrackedProduct.lowest_price.isnot(None),
                TrackedProduct.current_price <= TrackedProduct.lowest_price,
            )
        )
    elif status == "paused":
        query = query.where(TrackedProduct.tracking_enabled.is_(False))

    if store_slug:
        query = query.join(Store, TrackedProduct.store_id == Store.id).where(Store.slug == store_slug)

    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(or_(TrackedProduct.name.ilike(pattern), TrackedProduct.brand.ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0

    if sort == "price_drop":
        # Largest saving first. Computed rather than stored because it depends
        # on two columns that both move.
        order = (TrackedProduct.original_price - TrackedProduct.current_price).desc().nulls_last()
    elif sort == "discount":
        order = (
            (TrackedProduct.original_price - TrackedProduct.current_price)
            / func.nullif(TrackedProduct.original_price, 0)
        ).desc().nulls_last()
    else:
        order = SORTABLE.get(sort, SORTABLE["recent"])

    query = query.options(selectinload(TrackedProduct.variants)).order_by(order).limit(limit).offset(offset)
    return list(db.scalars(query).unique()), total


def get_product(db: Session, user: User, product_id: int) -> TrackedProduct | None:
    return db.scalars(
        select(TrackedProduct)
        .where(TrackedProduct.id == product_id, TrackedProduct.user_id == user.id)
        .options(selectinload(TrackedProduct.variants))
    ).first()


def update_product(db: Session, product: TrackedProduct, payload: ProductUpdate) -> TrackedProduct:
    for field in (
        "tracking_enabled",
        "price_tracking_enabled",
        "stock_tracking_enabled",
        "notify_email",
        "notify_browser",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(product, field, value)

    if payload.target_price is not None:
        product.target_price = payload.target_price

    if payload.watched_variant_ids is not None:
        watched = set(payload.watched_variant_ids)
        for variant in product.variants:
            variant.is_watched = variant.variant_id in watched

    # Resuming should check soon rather than waiting out the old schedule.
    if payload.tracking_enabled:
        product.next_check_at = utcnow()

    db.flush()
    return product


def overview(db: Session, user: User) -> OverviewOut:
    """The dashboard's headline numbers, in one pass per metric."""
    base = select(func.count(TrackedProduct.id)).where(TrackedProduct.user_id == user.id)

    def count_where(*conditions) -> int:  # noqa: ANN002
        return db.scalar(base.where(*conditions)) or 0

    week_ago = utcnow() - timedelta(days=7)

    price_drops = (
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.created_at >= week_ago,
                Notification.type.in_(
                    [
                        NotificationType.PRICE_DROP.value,
                        NotificationType.TARGET_PRICE_REACHED.value,
                        NotificationType.LOWEST_PRICE_REACHED.value,
                    ]
                ),
            )
        )
        or 0
    )
    back_in_stock = (
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id,
                Notification.created_at >= week_ago,
                Notification.type.in_(
                    [
                        NotificationType.STOCK_AVAILABLE.value,
                        NotificationType.COMBINED_STOCK_AND_PRICE.value,
                    ]
                ),
            )
        )
        or 0
    )
    unread = (
        db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id, Notification.read_at.is_(None)
            )
        )
        or 0
    )

    # "Saved" is the sum of (original - current) across everything currently
    # discounted: what the user would save buying it all right now.
    saved = (
        db.scalar(
            select(func.coalesce(func.sum(TrackedProduct.original_price - TrackedProduct.current_price), 0)).where(
                TrackedProduct.user_id == user.id,
                TrackedProduct.original_price.isnot(None),
                TrackedProduct.current_price.isnot(None),
                TrackedProduct.current_price < TrackedProduct.original_price,
            )
        )
        or Decimal("0")
    )

    currency = db.scalar(
        select(TrackedProduct.currency)
        .where(TrackedProduct.user_id == user.id, TrackedProduct.currency.isnot(None))
        .group_by(TrackedProduct.currency)
        .order_by(func.count(TrackedProduct.id).desc())
        .limit(1)
    )

    return OverviewOut(
        tracked_total=count_where(),
        tracking_active=count_where(TrackedProduct.tracking_enabled.is_(True)),
        in_stock=count_where(TrackedProduct.availability == StockStatus.IN_STOCK.value),
        out_of_stock=count_where(TrackedProduct.availability == StockStatus.OUT_OF_STOCK.value),
        unknown_stock=count_where(TrackedProduct.availability == StockStatus.UNKNOWN.value),
        price_drops_7d=price_drops,
        back_in_stock_7d=back_in_stock,
        at_lowest_price=count_where(
            TrackedProduct.current_price.isnot(None),
            TrackedProduct.lowest_price.isnot(None),
            TrackedProduct.current_price <= TrackedProduct.lowest_price,
        ),
        unread_notifications=unread,
        total_saved=Decimal(str(saved)),
        currency=currency,
    )


def price_history(db: Session, product: TrackedProduct, days: int | None) -> list[PriceHistory]:
    query = select(PriceHistory).where(PriceHistory.tracked_product_id == product.id)
    if days:
        query = query.where(PriceHistory.recorded_at >= utcnow() - timedelta(days=days))
    return list(db.scalars(query.order_by(PriceHistory.recorded_at.asc())))


def stock_history(db: Session, product: TrackedProduct, limit: int = 200) -> list[tuple[StockHistory, TrackedVariant]]:
    rows = db.execute(
        select(StockHistory, TrackedVariant)
        .join(TrackedVariant, StockHistory.tracked_variant_id == TrackedVariant.id)
        .where(TrackedVariant.tracked_product_id == product.id)
        .order_by(StockHistory.recorded_at.desc())
        .limit(limit)
    ).all()
    return [(row[0], row[1]) for row in rows]
