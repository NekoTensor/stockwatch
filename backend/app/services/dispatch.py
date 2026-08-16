"""Getting a check to happen now, rather than at the next sweep.

A product that has just been tracked has no price, no history and no verdict,
and the dashboard can only say "Not checked yet" until something looks at it.
Waiting for the next scheduled sweep to fix that is the wrong answer twice
over: it is the first thing a new user sees, and it is the one check whose
timing they are actually watching.

Two routes out, because there are two deployments. Where Celery is running the
work goes to the queue and the request returns immediately. Where there is no
broker — a free host with no Redis — it runs in the API process after the
response has been sent. Same function either way; only who calls it differs.
"""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks

from app.config import settings

logger = logging.getLogger(__name__)


def run_check(product_id: int) -> None:
    """Check one product in its own session.

    Imports are local because this runs in a background thread and in a Celery
    worker, and neither should pay for the monitoring stack at import time.
    """
    from app.database.session import session_scope
    from app.models import TrackedProduct
    from app.monitoring.engine import check_product

    with session_scope() as db:
        product = db.get(TrackedProduct, product_id)
        if product is None or not product.tracking_enabled:
            return
        check_product(db, product, send_email=True)


def request_check(product_id: int, background: BackgroundTasks | None = None) -> str:
    """Ask for a check as soon as possible. Returns how it was arranged.

    Never raises: a product that has been tracked has been tracked, and failing
    the request because the queue is unreachable would lose the user's work
    over something the next sweep will pick up anyway.
    """
    if not settings.check_on_track:
        return "disabled"

    try:
        from app.worker import check_one

        # retry=False so an unreachable broker fails here, in a millisecond,
        # instead of blocking the request while Celery retries the connection.
        check_one.apply_async(args=[product_id], retry=False)
        return "queued"
    except Exception as exc:  # noqa: BLE001 - any broker failure means fall back
        logger.info("Queue unavailable (%s); checking in-process", type(exc).__name__)

    if background is not None:
        background.add_task(run_check, product_id)
        return "background"

    # Nothing to run it on. The scheduled sweep still will.
    return "deferred"
