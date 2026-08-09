from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@router.get("/health/ready")
def ready(db: DbSession) -> dict[str, str]:
    """Readiness, not liveness: reports whether the database is reachable."""
    try:
        db.execute(select(1))
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "database": f"{type(exc).__name__}: {exc}"}
    return {"status": "ok", "database": "ok"}
