# TLDRDigest

Personal app that pulls **TLDR Tech / AI / DevOps / Dev** weekly newsletters from Yahoo Mail, stores every article in Postgres+pgvector, and generates dark-themed HTML digests with a .NET-architect lens.

## Requirements

| Component | Version | Notes |
|---|---|---|
| **PostgreSQL** | 13+ (16 recommended) | Must have the **pgvector** extension — the stock `postgres` image does **not**. |
| **pgvector** | 0.5.0+ (0.8.x recommended) | Trusted extension; the migration runs `CREATE EXTENSION` itself. |
| **Python** | 3.12+ | Only for running outside Docker (3.13 confirmed). |
| **LLM** | — | An Anthropic API key, and/or Ollama running locally. |
| **Yahoo** | — | An app password: <https://login.yahoo.com/account/security/app-passwords> |

**Deploying against a server (e.g. Postgres on Unraid)? → see [DEPLOY.md](DEPLOY.md).**
It covers getting pgvector onto your Postgres, version matching, and the Unraid walkthrough.

## Quick start — Docker (recommended)

```bash
cp .env.example .env
# edit .env: DATABASE_URL (your Postgres), YAHOO_APP_PASSWORD, ANTHROPIC_API_KEY

docker compose up -d --build          # app waits for DB, runs migrations, serves :8080
docker compose exec app tldr fetch    # pull this week's TLDR emails
docker compose exec app tldr enrich   # summarize + embed
docker compose exec app tldr report --source tldr_ai
# open http://<host>:8080
```

No Postgres yet? Spin up a throwaway local one: `docker compose --profile local-db up -d`
(then set `DATABASE_URL=postgresql+asyncpg://tldr:tldr@localhost:5433/tldr`).

## Quick start — Python (no Docker)

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env                  # edit: DATABASE_URL, YAHOO_APP_PASSWORD, ANTHROPIC_API_KEY
alembic upgrade head                  # create schema + extensions
tldr fetch                            # pull emails
tldr enrich --provider claude         # summarize + embed
tldr report --source tldr_ai          # write HTML report
tldr serve                            # web UI on :8080
```

## Web UI

| Route | Purpose |
|---|---|
| `/` | Dashboard — recent articles, tag chips, `Reviewed` checkboxes |
| `/inbox` | Every fetched email with fetch/enrich/report status; primary "what's processed" screen |
| `/articles/{id}` | Article detail, similar articles, tags |
| `/search` | Keyword + semantic search |
| `/reports` | Past HTML reports, regenerate button |
| `/settings` | LLM provider toggle (Claude/Ollama), model + API key config |

## CLI

```
tldr fetch [--since 7d] [--source tldr_ai]
tldr enrich [--provider claude|ollama] [--limit 50]
tldr report --source tldr_ai [--week current|YYYY-Www]
tldr embed --backfill
```
