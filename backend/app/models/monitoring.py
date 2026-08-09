from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, utcnow
from app.models.enums import JobStatus


class MonitoringJob(Base):
    """One audit row per check attempt.

    Worth the storage: when a store changes its markup, this table is how you
    find out *when* it started failing and whether it is one store or all of
    them. It is also what feeds the per-product backoff.
    """

    __tablename__ = "monitoring_jobs"
    __table_args__ = (Index("ix_monitoring_jobs_product_time", "tracked_product_id", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_product_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_products.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(20), default=JobStatus.PENDING, nullable=False)
    #: The CheckStatus the monitor concluded with (ok/partial/failed/blocked...).
    check_status: Mapped[str | None] = mapped_column(String(20))

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    http_status: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    adapter: Mapped[str | None] = mapped_column(String(64))
    layers_used: Mapped[str | None] = mapped_column(String(255))

    changes_detected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notifications_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MonitoringJob {self.id} {self.status}>"
