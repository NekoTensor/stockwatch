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


def send_notification_email(notification: Notification, price_context: str = "") -> bool:
    """Send one alert. Returns whether it went out.

    The delivery stamp is written onto the (already attached) notification
    rather than committed here, so it lands in whatever transaction the caller
    is running. The caller commits.
    """
    product = notification.product
    user = notification.user

    if not settings.email_enabled:
        notification.email_error = "Email delivery is off (set RESEND_API_KEY, or EMAIL_ENABLED=true)."
        return False
    if not user.email_notifications or not product.notify_email:
        notification.email_error = "Email disabled for this user or product."
        return False

    try:
        resend = _client()
        html, text = render_email(notification, product, price_context)
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


def send_auth_email(to: str, subject: str, heading: str, code: str, note: str) -> bool:
    """Send one account code. Returns whether it went.

    Deliberately plain: no product imagery, no marketing, nothing to click. An
    email carrying a credential should look like the thing it is, and a reader
    deciding whether it is a phishing attempt should have nothing to weigh up
    but the code itself.
    """
    if not settings.email_enabled:
        logger.warning("Cannot send %s to %s: email delivery is off.", subject, to)
        return False

    html = (
        f'<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:480px">'
        f'<p style="font-size:15px;color:#111">{heading}</p>'
        f'<p style="font-size:28px;letter-spacing:4px;font-weight:600;color:#111;'
        f'margin:24px 0">{code}</p>'
        f'<p style="font-size:13px;color:#666;line-height:1.6">{note}</p>'
        f'<p style="font-size:12px;color:#999;margin-top:32px">StockWatch</p>'
        f"</div>"
    )
    text = f"{heading}\n\n{code}\n\n{note}\n\nStockWatch"

    try:
        resend = _client()
        resend.Emails.send(
            {"from": settings.email_from, "to": [to], "subject": subject, "html": html, "text": text}
        )
    except Exception as exc:  # noqa: BLE001 - provider errors must not escape
        logger.exception("Failed to send %s to %s: %s", subject, to, exc)
        return False

    logger.info("Sent %s to %s", subject, to)
    return True
