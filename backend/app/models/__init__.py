"""Model package.

Every model is imported here so that `Base.metadata` is complete no matter
which module the application happens to import first — Alembic autogenerate and
`create_all` both depend on that.
"""

from app.models.auth_token import AuthToken
from app.models.discord_link import DiscordLinkCode
from app.models.enums import (
    CheckStatus,
    ConditionCombine,
    JobStatus,
    NotificationChannel,
    NotificationPriority,
    NotificationType,
    PriceCondition,
    PriceVerdict,
    StockCondition,
    StockStatus,
    VariantType,
)
from app.models.history import PriceHistory, StockHistory
from app.models.monitoring import MonitoringJob
from app.models.notification import Notification
from app.models.product import TrackedProduct, TrackedVariant
from app.models.store import Store
from app.models.user import User
from app.models.watch_rule import WatchRule

__all__ = [
    "AuthToken",
    "CheckStatus",
    "ConditionCombine",
    "DiscordLinkCode",
    "JobStatus",
    "MonitoringJob",
    "Notification",
    "NotificationChannel",
    "NotificationPriority",
    "NotificationType",
    "PriceCondition",
    "PriceHistory",
    "PriceVerdict",
    "StockCondition",
    "StockHistory",
    "StockStatus",
    "Store",
    "TrackedProduct",
    "TrackedVariant",
    "User",
    "VariantType",
    "WatchRule",
]
