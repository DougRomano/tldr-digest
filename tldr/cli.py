from __future__ import annotations

import asyncio
import logging
from typing import Optional

import typer

from tldr.db.models import LLMProviderName, SourceName

app = typer.Typer(help="TLDRDigest CLI", no_args_is_help=True, add_completion=False)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
)


@app.command()
def fetch(
    since: int = typer.Option(7, "--since", help="Days of history to scan (IMAP date filter)"),
):
    """Pull TLDR Tech/AI/DevOps/Dev emails from Yahoo IMAP into Postgres."""
    from tldr.ingest.service import run_fetch

    stats = asyncio.run(run_fetch(since_days=since))
    typer.echo(
        f"emails={stats.emails_seen} inserted={stats.issues_inserted} skipped={stats.issues_skipped} articles={stats.articles_inserted}"
    )


@app.command()
def enrich(
    limit: int = typer.Option(50, "--limit", help="Max articles to enrich this run"),
    provider: Optional[str] = typer.Option(None, "--provider", help="claude | ollama (overrides setting)"),
    source: Optional[str] = typer.Option(
        None, "--source", help="Limit to one newsletter: tldr_tech | tldr_ai | tldr_devops | tldr_dev"
    ),
):
    """Run summarize + embed for pending articles."""
    from tldr.llm.enrich import run_enrich

    p_override = LLMProviderName(provider) if provider else None
    src = SourceName(source) if source else None
    stats = asyncio.run(run_enrich(limit=limit, provider_override=p_override, source=src))
    typer.echo(
        f"summarized={stats.summarized} embedded={stats.embedded} failed={stats.failed} skipped={stats.skipped}"
    )
    for err in stats.errors[:5]:
        typer.echo(f"  err: {err}")


@app.command()
def report(
    source: str = typer.Option(..., "--source", help="tldr_tech | tldr_ai | tldr_devops | tldr_dev"),
    provider: Optional[str] = typer.Option(None, "--provider"),
):
    """Generate a dark-themed HTML report into Branding/."""
    from tldr.reports.generator import generate_report

    src = SourceName(source)
    p_override = LLMProviderName(provider) if provider else None
    stats = asyncio.run(generate_report(src, provider_override=p_override))
    typer.echo(f"wrote {stats.file_path} ({stats.article_count} articles from {stats.issue_count} issues)")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
):
    """Run the web UI."""
    import uvicorn

    uvicorn.run("tldr.main:app", host=host, port=port, reload=False)


@app.command()
def doctor():
    """Quick sanity check of env + DB."""
    import asyncio as _asyncio

    from sqlalchemy import text

    from tldr.config import settings
    from tldr.db.session import engine

    typer.echo(f"DB URL: {settings.database_url}")
    typer.echo(f"Yahoo user: {settings.yahoo_user}  (password set: {bool(settings.yahoo_app_password)})")
    typer.echo(f"Anthropic key set: {bool(settings.anthropic_api_key)}")
    typer.echo(f"Ollama host: {settings.ollama_host}")
    typer.echo(f"Reports dir: {settings.reports_dir}")

    async def _ping():
        async with engine.connect() as conn:
            ver = (await conn.execute(text("select version()"))).scalar()
            ext = (await conn.execute(text("select extname from pg_extension where extname in ('vector','pg_trgm')"))).scalars().all()
            typer.echo(f"DB: {ver}")
            typer.echo(f"Extensions: {sorted(ext)}")

    _asyncio.run(_ping())


if __name__ == "__main__":
    app()
