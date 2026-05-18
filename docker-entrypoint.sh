#!/usr/bin/env bash
# Entrypoint: wait for Postgres, run migrations, then dispatch.
#
#   serve              -> run migrations + start the web UI (default)
#   fetch|enrich|...   -> run the matching `tldr` CLI command (no web server)
#
# Examples (Unraid):
#   docker exec tldr-digest /app/docker-entrypoint.sh fetch
#   docker exec tldr-digest tldr enrich --provider claude
set -euo pipefail

wait_for_db() {
  echo "[entrypoint] waiting for Postgres..."
  for i in $(seq 1 30); do
    if tldr doctor >/dev/null 2>&1; then
      echo "[entrypoint] Postgres reachable."
      return 0
    fi
    sleep 2
  done
  echo "[entrypoint] WARNING: could not confirm Postgres after 60s — continuing anyway."
}

run_migrations() {
  if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    echo "[entrypoint] running alembic migrations..."
    alembic upgrade head
  else
    echo "[entrypoint] RUN_MIGRATIONS=0 — skipping migrations."
  fi
}

cmd="${1:-serve}"

case "$cmd" in
  serve)
    wait_for_db
    run_migrations
    echo "[entrypoint] starting web UI on 0.0.0.0:${WEB_PORT:-8080}"
    exec uvicorn tldr.main:app --host 0.0.0.0 --port "${WEB_PORT:-8080}"
    ;;
  migrate)
    wait_for_db
    exec alembic upgrade head
    ;;
  *)
    # Treat anything else as a `tldr` subcommand: fetch, enrich, report, doctor...
    exec tldr "$@"
    ;;
esac
