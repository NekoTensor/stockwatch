from __future__ import annotations

from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import CurrentUser, DbSession
from app.detection.pipeline import detect_product
from app.models import TrackedProduct
from app.monitoring.fetcher import fetch_page
from app.schemas.common import Page
from app.schemas.product import (
    DetectRequest,
    OverviewOut,
    PriceHistoryOut,
    PricePoint,
    ProductDetail,
    ProductOut,
    ProductSnapshotOut,
    ProductUpdate,
    StockHistoryOut,
    StockPoint,
    TrackRequest,
    VariantIn,
)
from app.services import products as service
from app.services.price_stats import RANGE_DAYS, compute_stats

router = APIRouter(prefix="/products", tags=["products"])


def _to_out(product: TrackedProduct) -> ProductOut:
    out = ProductOut.model_validate(product)
    out.discount_percentage = product.discount_percentage
    if product.store:
        out.store = product.store.name
        out.store_slug = product.store.slug
    out.verdict = product.quick_verdict()
    out.active_rule_count = sum(1 for rule in product.watch_rules if rule.is_active)
    return out


def _require(db, user, product_id: int) -> TrackedProduct:  # noqa: ANN001
    product = service.get_product(db, user, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found.")
    return product


@router.post("/detect", response_model=ProductSnapshotOut)
def detect(payload: DetectRequest, user: CurrentUser) -> ProductSnapshotOut:  # noqa: ARG001
    """Server-side detection for a URL.

    The extension does not need this - it reads the page it is already on, which
    is both faster and works on pages that require a session. This exists for
    clients that cannot run an extension, and as a way to reproduce what the
    monitor sees.
    """
    url = str(payload.url)
    try:
        result = fetch_page(url)
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not fetch the page: {exc}") from exc

    if not result.ok:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            result.error or "Could not fetch the page.",
        )

    snapshot = detect_product(result.html or "", result.final_url or url)

    return ProductSnapshotOut(
        url=snapshot.url,
        store=snapshot.store_name,
        store_slug=snapshot.store_slug,
        name=snapshot.name,
        brand=snapshot.brand,
        category=snapshot.category,
        product_id=snapshot.product_id,
        sku=snapshot.sku,
        image_url=snapshot.image_url,
        currency=snapshot.currency,
        current_price=snapshot.current_price,
        original_price=snapshot.original_price,
        discount_percentage=snapshot.discount_percentage,
        availability=snapshot.availability,
        variants=[
            VariantIn(
                id=variant.id,
                name=variant.name,
                type=variant.type,
                availability=variant.availability,
                sku=variant.sku,
                price=variant.price,
            )
            for variant in snapshot.variants
        ],
        confidence=snapshot.confidence,
        adapter=snapshot.adapter,
        layers_used=snapshot.layers_used,
        provenance=snapshot.provenance,
        warnings=snapshot.warnings,
    )


@router.post("/track", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def track(payload: TrackRequest, user: CurrentUser, db: DbSession) -> ProductOut:
    product = service.track_product(db, user, payload)
    db.commit()
    db.refresh(product)
    return _to_out(product)


@router.get("", response_model=Page[ProductOut])
def list_tracked(
    user: CurrentUser,
    db: DbSession,
    status_filter: Annotated[
        Literal["all", "in_stock", "out_of_stock", "unknown", "price_drop", "lowest_price", "paused"],
        Query(alias="status"),
    ] = "all",
    store: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
    sort: Annotated[
        Literal["recent", "updated", "price_drop", "lowest_price", "discount", "name"], Query()
    ] = "recent",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ProductOut]:
    items, total = service.list_products(
        db,
        user,
        status=None if status_filter == "all" else status_filter,
        store_slug=store,
        search=search,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return Page[ProductOut](items=[_to_out(product) for product in items], total=total, limit=limit, offset=offset)


@router.get("/overview", response_model=OverviewOut)
def get_overview(user: CurrentUser, db: DbSession) -> OverviewOut:
    return service.overview(db, user)


@router.get("/{product_id}", response_model=ProductDetail)
def get_one(product_id: int, user: CurrentUser, db: DbSession) -> ProductDetail:
    product = _require(db, user, product_id)
    return ProductDetail.model_validate(
        {**_to_out(product).model_dump(), "price_stats": compute_stats(db, product)}
    )


@router.patch("/{product_id}", response_model=ProductOut)
def patch(product_id: int, payload: ProductUpdate, user: CurrentUser, db: DbSession) -> ProductOut:
    product = _require(db, user, product_id)
    service.update_product(db, product, payload)
    db.commit()
    db.refresh(product)
    return _to_out(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete(product_id: int, user: CurrentUser, db: DbSession) -> Response:
    product = _require(db, user, product_id)
    # Cascades remove the variants, price/stock history and notifications.
    db.delete(product)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{product_id}/pause", response_model=ProductOut)
def pause(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    product = _require(db, user, product_id)
    service.update_product(db, product, ProductUpdate(tracking_enabled=False))
    db.commit()
    db.refresh(product)
    return _to_out(product)


@router.post("/{product_id}/resume", response_model=ProductOut)
def resume(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    product = _require(db, user, product_id)
    service.update_product(db, product, ProductUpdate(tracking_enabled=True))
    db.commit()
    db.refresh(product)
    return _to_out(product)


@router.post("/{product_id}/check", response_model=ProductOut)
def check_now(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    """Force a check immediately.

    Runs inline rather than through Celery so the caller gets the result, and is
    still subject to the same per-host throttle as scheduled checks.
    """
    from app.monitoring.engine import check_product

    product = _require(db, user, product_id)
    check_product(db, product, send_email=True)
    db.commit()
    db.refresh(product)
    return _to_out(product)


@router.get("/{product_id}/price-history", response_model=PriceHistoryOut)
def get_price_history(
    product_id: int,
    user: CurrentUser,
    db: DbSession,
    range_: Annotated[Literal["7d", "30d", "90d", "all"], Query(alias="range")] = "30d",
) -> PriceHistoryOut:
    product = _require(db, user, product_id)
    rows = service.price_history(db, product, RANGE_DAYS[range_])
    return PriceHistoryOut(
        product_id=product.id,
        currency=product.currency,
        range=range_,
        points=[PricePoint(price=row.price, recorded_at=row.recorded_at) for row in rows],
        stats=compute_stats(db, product),
    )


@router.get("/{product_id}/stock-history", response_model=StockHistoryOut)
def get_stock_history(product_id: int, user: CurrentUser, db: DbSession) -> StockHistoryOut:
    product = _require(db, user, product_id)
    rows = service.stock_history(db, product)
    return StockHistoryOut(
        product_id=product.id,
        points=[
            StockPoint(
                variant_id=variant.id,
                variant_name=variant.variant_name,
                stock_status=history.stock_status,
                previous_status=history.previous_status,
                recorded_at=history.recorded_at,
            )
            for history, variant in rows
        ],
    )
