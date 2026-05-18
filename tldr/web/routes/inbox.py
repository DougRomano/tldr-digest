"""/inbox — the primary 'what's processed vs not' screen.

Lists every fetched newsletter_issue with fetch/enrich/report status, color-coded
rows, manual `Reviewed` checkbox, and Re-parse/Re-enrich action buttons.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tldr.db.models import (
    ArticleEnrichStatus,
    EnrichStatus,
    FetchStatus,
    NewsletterIssue,
    ReportStatus,
)
from tldr.db.session import get_session
from tldr.web.templates import templates

router = APIRouter()


def _row_class(issue: NewsletterIssue) -> str:
    if issue.fetch_status == FetchStatus.failed or issue.enrich_status == EnrichStatus.failed:
        return "row-fail"
    if issue.enrich_status == EnrichStatus.completed and issue.reviewed:
        return "row-ok"
    if issue.enrich_status == EnrichStatus.partial:
        return "row-warn"
    if issue.fetch_status == FetchStatus.pending or issue.enrich_status == EnrichStatus.pending:
        return "row-pend"
    return "row-pend"


@router.get("/inbox", response_class=HTMLResponse)
async def inbox(
    request: Request,
    f: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """f = filter pill: all | pending | failed | unreviewed | reviewed"""
    stmt = (
        select(NewsletterIssue)
        .options(selectinload(NewsletterIssue.articles))
        .order_by(NewsletterIssue.received_at.desc())
        .limit(200)
    )
    if f == "pending":
        stmt = stmt.where(
            (NewsletterIssue.fetch_status == FetchStatus.pending)
            | (NewsletterIssue.enrich_status == EnrichStatus.pending)
            | (NewsletterIssue.enrich_status == EnrichStatus.in_progress)
        )
    elif f == "failed":
        stmt = stmt.where(
            (NewsletterIssue.fetch_status == FetchStatus.failed)
            | (NewsletterIssue.enrich_status == EnrichStatus.failed)
            | (NewsletterIssue.enrich_status == EnrichStatus.partial)
        )
    elif f == "unreviewed":
        stmt = stmt.where(NewsletterIssue.reviewed.is_(False))
    elif f == "reviewed":
        stmt = stmt.where(NewsletterIssue.reviewed.is_(True))

    issues = (await session.execute(stmt)).scalars().all()

    # KPIs across full set (not the filtered view)
    total = await session.scalar(select(func.count()).select_from(NewsletterIssue)) or 0
    completed = await session.scalar(
        select(func.count()).select_from(NewsletterIssue).where(
            NewsletterIssue.enrich_status == EnrichStatus.completed
        )
    ) or 0
    failed = await session.scalar(
        select(func.count()).select_from(NewsletterIssue).where(
            (NewsletterIssue.fetch_status == FetchStatus.failed)
            | (NewsletterIssue.enrich_status == EnrichStatus.failed)
        )
    ) or 0
    unreviewed = await session.scalar(
        select(func.count()).select_from(NewsletterIssue).where(NewsletterIssue.reviewed.is_(False))
    ) or 0

    rows = []
    for issue in issues:
        rows.append(
            {
                "issue": issue,
                "row_class": _row_class(issue),
                "enriched_summary": f"{issue.articles_enriched}/{issue.articles_extracted}",
            }
        )

    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "active": "inbox",
            "rows": rows,
            "filter": f or "all",
            "kpis": {
                "total": total,
                "completed": completed,
                "failed": failed,
                "unreviewed": unreviewed,
            },
        },
    )


@router.post("/inbox/{issue_id}/review", response_class=HTMLResponse)
async def toggle_review(
    issue_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    issue = await session.get(NewsletterIssue, issue_id)
    if issue is None:
        return HTMLResponse("not found", status_code=404)
    issue.reviewed = not issue.reviewed
    issue.reviewed_at = datetime.now(timezone.utc) if issue.reviewed else None
    await session.commit()
    return templates.TemplateResponse(
        request,
        "_review_cell.html",
        {"issue": issue, "scope": "issue"},
    )


@router.post("/inbox/{issue_id}/reenrich", response_class=HTMLResponse)
async def reenrich_issue(
    issue_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    issue = await session.get(
        NewsletterIssue, issue_id, options=[selectinload(NewsletterIssue.articles)]
    )
    if issue is None:
        return HTMLResponse("not found", status_code=404)
    for a in issue.articles:
        if a.enrich_status in (ArticleEnrichStatus.failed, ArticleEnrichStatus.pending):
            a.enrich_status = ArticleEnrichStatus.pending
            a.enrich_error = None
    issue.enrich_status = EnrichStatus.pending
    await session.commit()

    # Kick off enrich in the background (fire-and-forget so the UI returns fast)
    from tldr.llm.enrich import run_enrich

    asyncio.create_task(run_enrich(limit=len(issue.articles)))
    return HTMLResponse(
        f'<span class="status s-in-progress">QUEUED</span>'
    )


@router.post("/inbox/fetch", response_class=HTMLResponse)
async def trigger_fetch(request: Request):
    from tldr.ingest.service import run_fetch

    stats = await run_fetch(since_days=7)
    return HTMLResponse(
        f'<div class="toast">fetched {stats.emails_seen} emails, '
        f"{stats.issues_inserted} new ({stats.articles_inserted} articles)</div>"
        '<script>setTimeout(()=>location.reload(), 800)</script>'
    )
