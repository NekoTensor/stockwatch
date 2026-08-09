"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, health, notifications, products
from app.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("stockwatch")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    problems = settings.check_production()
    if problems:
        for problem in problems:
            logger.error("Configuration: %s", problem)
        raise RuntimeError("Refusing to start with an unsafe production configuration.")

    if not settings.is_production and settings.database_url.startswith("sqlite"):
        # Convenience for local runs and tests only. Postgres uses Alembic.
        from app.database.base import Base
        from app.database.session import engine

        Base.metadata.create_all(engine)
        logger.info("SQLite schema ensured (development only).")

    logger.info("StockWatch API starting in %s mode", settings.environment)
    yield
    logger.info("StockWatch API shutting down")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Universal product tracking: detection, price history, variant-level "
        "stock monitoring and alerts."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)


def _cors_regex() -> str | None:
    """Translate the wildcard origins in settings into one regex.

    `chrome-extension://*` cannot be expressed in `allow_origins` because the
    extension's id is unknown until it is installed, and allowing `*` alongside
    credentials is rejected by browsers.
    """
    patterns: list[str] = []
    for origin in settings.cors_origins:
        if "*" in origin:
            patterns.append(re.escape(origin).replace(r"\*", ".*"))
    return "|".join(f"^{pattern}$" for pattern in patterns) if patterns else None


app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in settings.cors_origins if "*" not in origin],
    allow_origin_regex=_cors_regex(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# `exc` is unused but required: Starlette calls handlers with (request, exc).
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    """Log the detail, return a generic message.

    Stack traces and driver errors are useful in logs and dangerous in
    responses; this keeps them on the right side of the boundary.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Something went wrong. The error has been logged."},
    )


app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(products.router, prefix=settings.api_prefix)
app.include_router(notifications.router, prefix=settings.api_prefix)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "health": f"{settings.api_prefix}/health"}
