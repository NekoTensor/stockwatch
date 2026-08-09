# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# lxml needs libxml2/libxslt at runtime; curl is used by the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libxml2 libxslt1.1 curl \
    && rm -rf /var/lib/apt/lists/*

# Requirements first so a code change does not invalidate the dependency layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Never run as root: a scraper is an internet-facing parser, which is exactly
# the kind of thing that should have as little privilege as possible.
RUN useradd --create-home --shell /usr/sbin/nologin stockwatch \
    && chown -R stockwatch:stockwatch /app
USER stockwatch

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
