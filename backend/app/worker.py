"""Celery application and the scheduled tasks.

Why the browser does not do this: an MV3 service worker is evicted after about
thirty seconds of idle, so it cannot hold a schedule; and a user's laptop is the
wrong place to poll a thousand product pages from. Everything recurring lives
here, on intervals that a store would consider polite.
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.database.session import session_scope
from app.monitoring.engine import check_product
from app.monitoring.scheduler import due_products, group_by_host

logger = logging.getLogger(__name__)

celery_app = Celery("stockwatch", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    # A monitoring task that dies mid-flight should not be re-delivered to
    # another worker that then re-fetches the same page.
    task_reject_on_worker_lost=False,
    worker_prefetch_multiplier=1,
    task_time_limit=600,
    task_soft_time_limit=540,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "dispatch-due-checks": {
            "task": "stockwatch.dispatch_due_checks",
            # Every minute, not every five. This decides how late a check can
            # be, not how often a store is hit — that is `next_check_at` per
            # product and the per-host throttle. A sweep that finds nothing due
            # costs one query.
            "schedule": 60.0,
        },
        "retry-failed-emails": {
            "task": "stockwatch.retry_failed_emails",
            "schedule": crontab(minute="*/30"),
        },
        "prune-history": {
            "task": "stockwatch.prune_history",
            "schedule": crontab(hour=3, minute=15),
        },
    },
)


@celery_app.task(name="stockwatch.dispatch_due_checks")
def dispatch_due_checks(limit: int = 200) -> dict[str, int]:
    """Find due products and fan them out, one task per host.

    Grouping by host is what keeps the politeness guarantee: all of a store's
    products are checked by a single task, in sequence, behind the per-host
    throttle. Fanning out per product would defeat it.
    """
    with session_scope() as db:
        products = due_products(db, limit=limit)
        grouped = group_by_host(products)
        payload = {host: [product.id for product in items] for host, items in grouped.items()}

    for host, product_ids in payload.items():
        check_host.delay(host, product_ids)

    logger.info("Dispatched %d product(s) across %d host(s)", sum(len(v) for v in payload.values()), len(payload))
    return {"products": sum(len(v) for v in payload.values()), "hosts": len(payload)}


@celery_app.task(name="stockwatch.check_host")
def check_host(host: str, product_ids: list[int]) -> dict[str, int]:
    """Check every due product on one host, sequentially.

    Not bound and not retried: a partial run has already written its results,
    and re-running the whole host would re-fetch pages that succeeded. Failures
    are handled per product by the backoff schedule instead.
    """
    checked = 0
    failed = 0

    for product_id in product_ids:
        try:
            with session_scope() as db:
                from app.models import TrackedProduct

                product = db.get(TrackedProduct, product_id)
                if product is None or not product.tracking_enabled:
                    continue
                job = check_product(db, product)
                checked += 1
                if job.status == "failed":
                    failed += 1
        except Exception:  # noqa: BLE001 - one bad product must not stop the host
            logger.exception("Check failed for product %s", product_id)
            failed += 1

    logger.info("host=%s checked=%d failed=%d", host, checked, failed)
    return {"checked": checked, "failed": failed}


@celery_app.task(name="stockwatch.check_one")
def check_one(product_id: int) -> dict[str, str]:
    """Check a single product. Used by the API's "check now"."""
    with session_scope() as db:
        from app.models import TrackedProduct

        product = db.get(TrackedProduct, product_id)
        if product is None:
            return {"status": "missing"}
        job = check_product(db, product)
        return {"status": job.status}


@celery_app.task(name="stockwatch.retry_failed_emails")
def retry_failed_emails(limit: int = 50) -> dict[str, int]:
    """Retry alerts whose email failed.

    Only alerts from the last day: a restock notice from a week ago is not worth
    delivering late.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from app.database.base import utcnow
    from app.models import Notification
    from app.notifications.email import send_notification_email

    sent = 0
    with session_scope() as db:
        rows = db.scalars(
            select(Notification)
            .where(
                Notification.email_sent_at.is_(None),
                Notification.email_error.isnot(None),
                Notification.created_at >= utcnow() - timedelta(days=1),
                Notification.is_test.is_(False),
            )
            .limit(limit)
        ).unique()

        for notification in rows:
            if send_notification_email(notification):
                sent += 1

    return {"sent": sent}


@celery_app.task(name="stockwatch.prune_history")
def prune_history(keep_days: int = 365) -> dict[str, int]:
    """Keep the series useful without letting it grow forever."""
    from datetime import timedelta

    from sqlalchemy import delete

    from app.database.base import utcnow
    from app.models import PriceHistory

    cutoff = utcnow() - timedelta(days=keep_days)
    with session_scope() as db:
        result = db.execute(delete(PriceHistory).where(PriceHistory.recorded_at < cutoff))
        removed = result.rowcount or 0

    logger.info("Pruned %d price observations older than %d days", removed, keep_days)
    return {"removed": removed}
