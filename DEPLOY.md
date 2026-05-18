# Deploying TLDRDigest against your Unraid Postgres

## TL;DR — what you need

| Requirement | Minimum | Recommended | Notes |
|---|---|---|---|
| **PostgreSQL** | 13 | **16** | Your existing Unraid Postgres is fine *version-wise*. |
| **pgvector extension** | 0.5.0 | **0.8.x** | **This is the catch.** The stock `postgres` Docker image does **not** include it. |
| **pg_trgm extension** | (bundled) | — | Ships with Postgres core; no install needed. |
| Docker / Compose | — | Unraid's built-in Docker + Compose Manager plugin | For running the app container. |

The app stores article embeddings in a `vector(1024)` column and queries them
with an `ivfflat` cosine index. **Without `pgvector` the schema migration fails**
on its very first statement (`CREATE EXTENSION vector`).

Good news: `pgvector` is a *trusted* extension, so the app's database **owner**
can run `CREATE EXTENSION` itself — the migration does this automatically. You do
**not** need superuser steps, as long as `pgvector` is installed in the Postgres
*image*.

---

## Step 1 — Get pgvector onto your Unraid Postgres

The public image you need is **`pgvector/pgvector:pgNN`** — it *is* the official
Postgres image at major version `NN`, with the pgvector extension files baked in.
It's a drop-in replacement for the stock `postgres:NN` image.

**Option A is recommended if you already run a `postgres:NN` container.**

### Option A — Swap your existing container's image (recommended)

This is a one-field change and is **non-destructive**: the data directory layout
is identical, so all existing databases (e.g. an `identity` DB) are untouched.
You must keep the **same major version** — the data dir is version-specific.

1. Find your current major version (it's usually in the image tag, e.g.
   `postgres:17` → 17; or run `SELECT version();`).
2. Unraid **Docker** tab → edit that container → **Repository** field:
   - `postgres:17` → `pgvector/pgvector:pg17`
   - `postgres:16` → `pgvector/pgvector:pg16`
   - `postgres:15` → `pgvector/pgvector:pg15`
   - `postgres:14` → `pgvector/pgvector:pg14`
   - `postgres:13` → `pgvector/pgvector:pg13`
3. Leave port, path, and variables unchanged. **Apply.** Unraid pulls the new
   image and recreates the container against the same data path.
4. Create a dedicated database + user for the app — open the container's
   **Console** and run `psql -U postgres`, then:
   ```sql
   CREATE USER tldr WITH PASSWORD 'choose-a-password';
   CREATE DATABASE tldr OWNER tldr;
   ```
   Use these in `DATABASE_URL` — do **not** reuse the superuser / an existing DB.

### Option B — Dedicated Postgres container

If you'd rather not touch your current Postgres at all, run a second one just
for TLDRDigest. Unraid **Docker** tab → **Add Container**:

| Field | Value |
|---|---|
| Repository | `pgvector/pgvector:pg16` |
| Network | `bridge` (or your custom Docker network) |
| Port | Container `5432` → Host `5432` (pick another host port if 5432 is taken) |
| Path | Container `/var/lib/postgresql/data` → Host `/mnt/user/appdata/tldr-postgres` |
| Variable | `POSTGRES_USER` = `tldr` |
| Variable | `POSTGRES_PASSWORD` = *(choose a password)* |
| Variable | `POSTGRES_DB` = `tldr` |

Apply. `pgvector/pgvector:pg16` *is* stock Postgres 16 with the extension baked in.

> Do **not** try to `pip`/`apt` pgvector into a running stock `postgres`
> container — it needs build tooling and won't survive a recreate. Swap the
> image instead.

### Verify pgvector is available

Connect to the `tldr` database and run:
```sql
SELECT * FROM pg_available_extensions WHERE name = 'vector';
```
You should see a row. If it's empty, the image doesn't have pgvector — recheck Step 1.

---

## Step 2 — Point the app at your Unraid Postgres

```bash
cp .env.example .env
```

Edit `.env`:
```ini
DATABASE_URL=postgresql+asyncpg://tldr:YOUR_PASSWORD@192.168.1.10:5432/tldr
```
- Replace `192.168.1.10` with your Unraid server's LAN IP (and the port from Step 1).
- If you run the **app container on the same Unraid box and Docker network** as
  Postgres, you can use the Postgres container name instead of the IP:
  `...@tldr-postgres:5432/tldr`.

Also set in `.env`: `YAHOO_APP_PASSWORD`, `ANTHROPIC_API_KEY` (and/or run Ollama),
and `REPORTS_HOST_DIR` (an Unraid share where HTML reports should land, e.g.
`/mnt/user/appdata/tldr-digest/reports`).

---

## Step 3 — Run the app

The app is a separate container from Postgres. It runs the web UI and the CLI.

```bash
docker compose up -d --build
```

On startup the container **waits for Postgres, runs `alembic upgrade head`**
(creates all tables, enables `vector` + `pg_trgm`, seeds tags), then serves the
web UI on port `8080`. Open `http://<unraid-ip>:8080`.

### Deploying on Unraid itself

Use the **Compose Manager** plugin (Community Applications): create a new stack,
paste this repo's `docker-compose.yml`, put your `.env` next to it, and hit
**Compose Up**. Or build the image once and add it as a normal Unraid container
(repository `tldr-digest:latest`, port `8080`, env-file mounted).

---

## Step 4 — Fetch / enrich / report

These are CLI commands inside the running container:

```bash
docker compose exec app tldr fetch              # pull last 7 days of TLDR emails
docker compose exec app tldr enrich             # summarize + embed pending articles
docker compose exec app tldr report --source tldr_ai
docker compose exec app tldr doctor             # sanity-check DB + env
```

### Schedule it weekly (Unraid User Scripts plugin)

Add a script that runs every Monday morning:
```bash
#!/bin/bash
docker exec tldr-digest tldr fetch
docker exec tldr-digest tldr enrich --provider claude
for s in tldr_tech tldr_ai tldr_devops tldr_dev; do
  docker exec tldr-digest tldr report --source "$s"
done
```

---

## Mac-local dev (no Unraid)

If you'd rather not touch Unraid while developing, spin up a throwaway
pgvector Postgres locally:
```bash
docker compose --profile local-db up -d
# then set DATABASE_URL=postgresql+asyncpg://tldr:tldr@localhost:5433/tldr
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Migration fails: `could not open extension control file ".../vector.control"` | Postgres image lacks pgvector — redo Step 1. |
| Migration fails: `permission denied to create extension "vector"` | The `tldr` user isn't the **owner** of the `tldr` database. Run `ALTER DATABASE tldr OWNER TO tldr;` as a superuser, or have a superuser run `CREATE EXTENSION vector;` once. |
| App can't connect: `connection refused` | Check the Unraid Postgres container exposes the port on the LAN, the IP/port in `DATABASE_URL` are right, and no firewall blocks it. |
| `tldr doctor` shows extensions `[]` | Extensions not yet created — they're created by `alembic upgrade head`. Run `docker compose exec app tldr migrate` or just restart the app container. |
| Embeddings look random / semantic search is poor | No real embedding model configured. Set `VOYAGE_API_KEY` (Claude path) or ensure Ollama has `mxbai-embed-large` pulled. The hash-fallback only exists so the pipeline completes. |
