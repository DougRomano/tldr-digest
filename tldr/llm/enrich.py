"""Walks pending articles, calls the active provider for summary + embedding."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from tldr.db.models import (
    Article,
    ArticleEmbedding,
    ArticleEnrichStatus,
    EnrichStatus,
    LLMProviderName,
    NewsletterIssue,
)
from tldr.db.session import session_scope
from tldr.llm.factory import get_provider

log = logging.getLogger(__name__)


@dataclass(slots=True)
class EnrichStats:
    summarized: int = 0
    embedded: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


async def _enrich_one(provider, article: Article, source_display: str) -> tuple[bool, str | None]:
    try:
        summary = await provider.summarize(
            title=article.title, snippet=article.raw_snippet, source=source_display
        )
        article.llm_summary = summary.summary
        article.llm_so_what = summary.so_what
        if summary.suggested_section:
            article.suggested_section = summary.suggested_section
        if summary.suggested_tags:
            article.suggested_tags = ",".join(summary.suggested_tags)
        article.enrich_status = ArticleEnrichStatus.summarized

        vec = await provider.embed(f"{article.title}\n\n{summary.summary}")
        article.embedding = ArticleEmbedding(
            vector=vec, model=provider.embed_model, provider=provider.name
        )
        article.enrich_status = ArticleEnrichStatus.embedded
        article.enriched_at = datetime.now(timezone.utc)
        return True, None
    except Exception as exc:  # noqa: BLE001 — surface every failure to the user
        article.enrich_status = ArticleEnrichStatus.failed
        article.enrich_error = f"{type(exc).__name__}: {exc}"
        return False, article.enrich_error


async def run_enrich(
    *, limit: int = 50, provider_override: LLMProviderName | None = None
) -> EnrichStats:
    stats = EnrichStats()
    async with session_scope() as s:
        provider = await get_provider(s, override=provider_override)
        log.info("enrich: using provider=%s chat=%s embed=%s", provider.name.value, provider.chat_model, provider.embed_model)

        pending = (
            await s.execute(
                select(Article)
                .where(Article.enrich_status == ArticleEnrichStatus.pending)
                .order_by(Article.id)
                .limit(limit)
                .options(selectinload(Article.issue))
            )
        ).scalars().all()

        if not pending:
            log.info("enrich: nothing pending")
            return stats

        # Mark parent issues as in_progress
        issue_ids = {a.issue_id for a in pending}
        await s.execute(
            update(NewsletterIssue)
            .where(NewsletterIssue.id.in_(issue_ids))
            .values(enrich_status=EnrichStatus.in_progress, enrich_provider=provider.name)
        )

        for a in pending:
            ok, err = await _enrich_one(provider, a, a.issue.source.value)
            if ok:
                stats.summarized += 1
                stats.embedded += 1
            else:
                stats.failed += 1
                if err:
                    stats.errors.append(err)
            # commit per article so progress is visible during a long run
            await s.flush()

        # Roll up per-issue status
        await _rollup_issue_status(s, issue_ids)

    log.info("enrich: done %s", stats)
    return stats


async def _rollup_issue_status(session, issue_ids: set[int]) -> None:
    """After enriching a batch, update each affected issue's enrich_status."""
    for iid in issue_ids:
        issue = await session.get(NewsletterIssue, iid, options=[selectinload(NewsletterIssue.articles)])
        if issue is None:
            continue
        statuses = [a.enrich_status for a in issue.articles]
        n_total = len(statuses)
        n_done = sum(1 for s in statuses if s == ArticleEnrichStatus.embedded)
        n_failed = sum(1 for s in statuses if s == ArticleEnrichStatus.failed)
        issue.articles_enriched = n_done
        if n_total == 0:
            issue.enrich_status = EnrichStatus.failed
        elif n_done == n_total:
            issue.enrich_status = EnrichStatus.completed
            issue.enriched_at = datetime.now(timezone.utc)
        elif n_done == 0 and n_failed == n_total:
            issue.enrich_status = EnrichStatus.failed
        elif n_failed > 0:
            issue.enrich_status = EnrichStatus.partial
        else:
            # mixed pending + done — leave in_progress
            issue.enrich_status = EnrichStatus.in_progress
