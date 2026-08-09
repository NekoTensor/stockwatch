"""The monitoring loop for one product.

    fetch -> detect -> compare -> persist -> notify

Every stage can fail, and the rule at every stage is the same: **a failure of
ours is not a fact about the product.** A check that could not complete leaves
the stored state exactly as it was, records why, and schedules a retry.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.database.base import utcnow
from app.detection.pipeline import detect_product
from app.models import MonitoringJob, Notification, TrackedProduct
from app.models.enums import CheckStatus, JobStatus
from app.monitoring.fetcher import FetchResult, fetch_page
from app.notifications import engine as notifications
from app.services.changes import ChangeSet, apply_snapshot

logger = logging.getLogger(__name__)


def next_check_delay(product: TrackedProduct, status: CheckStatus) -> timedelta:
    """When to look again.

    Healthy products use the store's interval. Failures back off exponentially
    so that a store having a bad day is not hammered, and a product that keeps
    failing drifts towards a check a day rather than being retried forever.
    """
    store_interval = product.store.check_interval_minutes if product.store else None
    base = store_interval or settings.check_interval_minutes

    if status is CheckStatus.OK:
        return timedelta(minutes=base)

    if status is CheckStatus.NOT_FOUND:
        # The page is gone. Keep the row (its history is still useful) but stop
        # asking often.
        return timedelta(hours=24)

    failures = max(1, product.consecutive_failures)
    if status is CheckStatus.BLOCKED:
        # Being blocked deserves a harsher penalty than a flaky connection.
        minutes = min(base * (3**failures), 24 * 60)
    else:
        minutes = min(base * (2**failures), 12 * 60)

    return timedelta(minutes=minutes)


def _record_failure(product: TrackedProduct, job: MonitoringJob, result: FetchResult) -> None:
    product.consecutive_failures += 1
    product.last_check_status = result.status.value
    product.last_error = result.error
    product.last_checked_at = utcnow()
    product.next_check_at = utcnow() + next_check_delay(product, result.status)

    job.status = JobStatus.FAILED.value
    job.check_status = result.status.value
    job.http_status = result.http_status
    job.attempts = result.attempts
    job.error = result.error

    if product.consecutive_failures >= settings.max_consecutive_failures:
        # Not disabled - just quiet. Disabling would lose the user's alert
        # settings for a store that is probably fine again next week.
        logger.warning(
            "Product %s has failed %d checks in a row (%s)",
            product.id,
            product.consecutive_failures,
            result.error,
        )


def check_product(db: Session, product: TrackedProduct, *, send_email: bool = True) -> MonitoringJob:
    """Run one full check. Always returns a job row describing what happened."""
    started = time.monotonic()
    job = MonitoringJob(tracked_product_id=product.id, status=JobStatus.RUNNING.value)
    db.add(job)
    db.flush()

    delay_override = product.store.min_request_delay_seconds if product.store else None
    result = fetch_page(product.url, delay_override=delay_override)

    if not result.ok:
        _record_failure(product, job, result)
        job.finished_at = utcnow()
        job.duration_ms = int((time.monotonic() - started) * 1000)
        return job

    try:
        snapshot = detect_product(result.html or "", result.final_url or product.url)
    except Exception as exc:  # noqa: BLE001 - a parse failure is a failed check
        logger.exception("Detection raised for product %s", product.id)
        _record_failure(
            product,
            job,
            FetchResult(
                status=CheckStatus.FAILED,
                http_status=result.http_status,
                attempts=result.attempts,
                error=f"Detection failed: {type(exc).__name__}: {exc}",
            ),
        )
        job.finished_at = utcnow()
        job.duration_ms = int((time.monotonic() - started) * 1000)
        return job

    job.adapter = snapshot.adapter
    job.layers_used = ",".join(snapshot.layers_used)[:255]
    job.http_status = result.http_status
    job.attempts = result.attempts

    if not snapshot.has_product:
        # The page came back but did not describe a product: an interstitial, a
        # bot wall, or a redirect to a category. Explicitly NOT a stock change.
        _record_failure(
            product,
            job,
            FetchResult(
                status=CheckStatus.PARTIAL,
                http_status=result.http_status,
                attempts=result.attempts,
                error="Page loaded but no product could be read from it.",
            ),
        )
        job.finished_at = utcnow()
        job.duration_ms = int((time.monotonic() - started) * 1000)
        return job

    changes: ChangeSet = apply_snapshot(db, product, snapshot)
    created: list[Notification] = notifications.evaluate(db, changes)

    product.consecutive_failures = 0
    product.last_error = None
    product.last_check_status = CheckStatus.OK.value
    product.last_checked_at = utcnow()
    product.next_check_at = utcnow() + next_check_delay(product, CheckStatus.OK)

    job.status = JobStatus.SUCCEEDED.value
    job.check_status = CheckStatus.OK.value
    job.changes_detected = int(changes.price_changed) + len(changes.variant_changes)
    job.notifications_created = len(created)
    job.finished_at = utcnow()
    job.duration_ms = int((time.monotonic() - started) * 1000)

    db.flush()

    if send_email and created:
        from app.notifications.email import send_notification_email

        for notification in created:
            send_notification_email(notification)

    return job
