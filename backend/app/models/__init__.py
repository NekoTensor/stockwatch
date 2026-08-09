"""Model package.

Every model is imported here so that `Base.metadata` is complete no matter
which module the application happens to import first — Alembic autogenerate and
`create_all` both depend on that.
"""

from app.models.enums import (
    CheckStatus,
    JobStatus,
    NotificationChannel,
    NotificationPriority,
    NotificationType,
    StockStatus,
    VariantType,
)
from app.models.history import PriceHistory, StockHistory
from app.models.monitoring import MonitoringJob
from app.models.notification import Notification
from app.models.product import TrackedProduct, TrackedVariant
from app.models.store import Store
from app.models.user import User

__all__ = [
    "CheckStatus",
    "JobStatus",
    "MonitoringJob",
    "Notification",
    "NotificationChannel",
    "NotificationPriority",
    "NotificationType",
    "PriceHistory",
    "StockHistory",
    "StockStatus",
    "Store",
    "TrackedProduct",
    "TrackedVariant",
    "User",
    "VariantType",
]
