# TLDRDigest — app container (web UI + CLI). Postgres lives elsewhere
# (your Unraid pgvector container). See DEPLOY.md.
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: libpq for asyncpg/psycopg, curl for the healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching).
COPY pyproject.toml README.md ./
COPY tldr ./tldr
RUN pip install .

# Alembic config + migrations live at repo root (outside the package).
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

# Reports are written here; mount a host path / Unraid share over it.
RUN mkdir -p /reports
ENV REPORTS_DIR=/reports

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["serve"]
