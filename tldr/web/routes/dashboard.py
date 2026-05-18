from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tldr.db.models import Article, ArticleEnrichStatus, NewsletterIssue, SourceName, Tag
from tldr.db.session import get_session
from tldr.web.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    source: Optional[str] = None,
    tag: Optional[str] = None,
    reviewed: Optional[str] = None,
    untagged: Optional[bool] = False,
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(Article)
        .options(selectinload(Article.issue), selectinload(Article.tags))
        .join(NewsletterIssue)
        .order_by(NewsletterIssue.received_at.desc(), Article.position.asc())
        .limit(120)
    )
    if source:
        stmt = stmt.where(NewsletterIssue.source == SourceName(source))
    if tag:
        stmt = stmt.where(Article.tags.any(Tag.name == tag))
    if reviewed == "yes":
        stmt = stmt.where(Article.reviewed.is_(True))
    elif reviewed == "no":
        stmt = stmt.where(Article.reviewed.is_(False))

    arts = (await session.execute(stmt)).scalars().all()
    if untagged:
        arts = [a for a in arts if not a.tags]

    all_tags = (await session.execute(select(Tag).order_by(Tag.name))).scalars().all()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "active": "dashboard",
            "articles": arts,
            "all_tags": all_tags,
            "source": source,
            "tag": tag,
            "reviewed": reviewed,
            "untagged": untagged,
            "sources": list(SourceName),
        },
    )
