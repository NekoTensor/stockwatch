"""Email delivery via Resend.

Failure to send is recorded on the notification and never raised: an email
outage must not roll back the state change that produced the alert, or the user
would be told about the same restock again on the next check.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.database.base import utcnow
from app.models import Notification
from app.notifications.templates import render_email, subject_for

logger = logging.getLogger(__name__)


class EmailNotConfigured(RuntimeError):
    pass


def _client():  # noqa: ANN202 - resend's module-level API has no exported type
    if not settings.resend_api_key:
        raise EmailNotConfigured("RESEND_API_KEY is not set.")
    import resend

    resend.api_key = settings.resend_api_key
    return resend


def send_notification_email(notification: Notification) -> bool:
    """Send one alert. Returns whether it went out.

    The delivery stamp is written onto the (already attached) notification
    rather than committed here, so it lands in whatever transaction the caller
    is running. The caller commits.
    """
    product = notification.product
    user = notification.user

    if not settings.email_enabled:
        notification.email_error = "Email delivery is disabled (EMAIL_ENABLED=false)."
        return False
    if not user.email_notifications or not product.notify_email:
        notification.email_error = "Email disabled for this user or product."
        return False

    try:
        resend = _client()
        html, text = render_email(notification, product)
        response = resend.Emails.send(
            {
                "from": settings.email_from,
                "to": [user.email],
                "subject": subject_for(notification),
                "html": html,
                "text": text,
            }
        )
    except EmailNotConfigured as exc:
        notification.email_error = str(exc)
        logger.warning("Email not configured: %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001 - provider errors must not escape
        notification.email_error = f"{type(exc).__name__}: {exc}"
        logger.exception("Failed to send notification %s", notification.id)
        return False

    notification.email_sent_at = utcnow()
    notification.email_error = None
    logger.info("Sent notification %s to %s (%s)", notification.id, user.email, response)
    return True
