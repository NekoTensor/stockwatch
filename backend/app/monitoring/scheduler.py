"""Choosing what to check next."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.base import utcnow
from app.models import TrackedProduct


def due_products(db: Session, limit: int = 200) -> list[TrackedProduct]:
    """Products whose next check is due.

    Ordered oldest-first so a backlog drains fairly instead of starving whatever
    happens to sort last. `next_check_at IS NULL` covers freshly tracked
    products, which should be checked promptly.
    """
    query = (
        select(TrackedProduct)
        .where(
            TrackedProduct.tracking_enabled.is_(True),
            or_(TrackedProduct.next_check_at.is_(None), TrackedProduct.next_check_at <= utcnow()),
        )
        .options(selectinload(TrackedProduct.variants))
        .order_by(TrackedProduct.next_check_at.asc().nulls_first(), TrackedProduct.id.asc())
        .limit(limit)
    )
    return list(db.scalars(query).unique())


def group_by_host(products: list[TrackedProduct]) -> dict[str, list[TrackedProduct]]:
    """Group so that one worker handles one store, keeping requests serialised."""
    from urllib.parse import urlparse

    grouped: dict[str, list[TrackedProduct]] = {}
    for product in products:
        host = urlparse(product.url).netloc
        grouped.setdefault(host, []).append(product)
    return grouped
