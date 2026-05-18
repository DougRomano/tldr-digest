"""Orchestrates fetch → parse → upsert into the DB."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tldr.db.models import (
    Article,
    FetchStatus,
    NewsletterIssue,
)
from tldr.db.session import session_scope
from tldr.ingest.imap_client import FetchedEmail, fetch_recent
from tldr.ingest.parser import BADGE_CLASS, parse_tldr_html

log = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestStats:
    emails_seen: int = 0
    issues_inserted: int = 0
    issues_skipped: int = 0
    articles_inserted: int = 0


async def _persist(session: AsyncSession, email: FetchedEmail) -> tuple[bool, int]:
    """Insert one email + its parsed articles. Idempotent on (imap_uid, imap_folder).

    Returns (inserted, n_articles).
    """
    existing = await session.scalar(
        select(NewsletterIssue).where(
            NewsletterIssue.imap_uid == email.imap_uid,
            NewsletterIssue.imap_folder == email.imap_folder,
        )
    )
    if existing is not None:
        return False, 0

    articles = parse_tldr_html(email.html, email.source)
    badge = BADGE_CLASS[email.source]
    issue = NewsletterIssue(
        source=email.source,
        subject=email.subject,
        received_at=email.received_at,
        raw_html=email.html,
        raw_text=email.text,
        imap_uid=email.imap_uid,
        imap_folder=email.imap_folder,
        fetch_status=FetchStatus.parsed if articles else FetchStatus.failed,
        fetched_at=datetime.now(timezone.utc),
        articles_extracted=len(articles),
        parse_error=None if articles else "no articles parsed",
        articles=[
            Article(
                title=a.title,
                url=a.url,
                raw_snippet=a.raw_snippet,
                read_time=a.read_time,
                position=a.position,
                suggested_section=a.suggested_section,
                badge_class=badge,
            )
            for a in articles
        ],
    )
    session.add(issue)
    return True, len(articles)


async def run_fetch(since_days: int = 7) -> IngestStats:
    stats = IngestStats()
    emails = await asyncio.to_thread(fetch_recent, since_days)
    stats.emails_seen = len(emails)
    async with session_scope() as s:
        for email in emails:
            inserted, n = await _persist(s, email)
            if inserted:
                stats.issues_inserted += 1
                stats.articles_inserted += n
            else:
                stats.issues_skipped += 1
    log.info(
        "ingest: emails=%d inserted=%d skipped=%d articles=%d",
        stats.emails_seen,
        stats.issues_inserted,
        stats.issues_skipped,
        stats.articles_inserted,
    )
    return stats
