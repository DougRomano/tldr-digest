from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tldr.db.models import Article, ArticleEmbedding, Tag
from tldr.db.session import get_session
from tldr.web.templates import templates

router = APIRouter()


@router.get("/articles/{aid}", response_class=HTMLResponse)
async def article_detail(
    aid: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    a = (
        await session.execute(
            select(Article)
            .where(Article.id == aid)
            .options(selectinload(Article.issue), selectinload(Article.tags), selectinload(Article.embedding))
        )
    ).scalar_one_or_none()
    if a is None:
        return HTMLResponse("not found", status_code=404)
    all_tags = (await session.execute(select(Tag).order_by(Tag.name))).scalars().all()

    similar: list[Article] = []
    if a.embedding is not None:
        # pgvector cosine distance; lower is closer
        stmt = (
            select(Article)
            .join(ArticleEmbedding, ArticleEmbedding.article_id == Article.id)
            .where(Article.id != a.id)
            .order_by(ArticleEmbedding.vector.cosine_distance(a.embedding.vector))
            .limit(5)
            .options(selectinload(Article.issue))
        )
        similar = (await session.execute(stmt)).scalars().all()

    return templates.TemplateResponse(
        request,
        "article.html",
        {"active": "dashboard", "a": a, "all_tags": all_tags, "similar": similar},
    )


@router.post("/articles/{aid}/review", response_class=HTMLResponse)
async def toggle_review(aid: int, session: AsyncSession = Depends(get_session)):
    a = await session.get(Article, aid)
    if a is None:
        return HTMLResponse("not found", status_code=404)
    a.reviewed = not a.reviewed
    a.reviewed_at = datetime.now(timezone.utc) if a.reviewed else None
    await session.commit()
    return HTMLResponse(
        f'<span class="reviewed-pill" style="color:#34d399">{"reviewed" if a.reviewed else ""}</span>'
    )


@router.post("/articles/{aid}/tag", response_class=HTMLResponse)
async def toggle_tag(
    aid: int,
    name: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    a = await session.get(Article, aid, options=[selectinload(Article.tags)])
    if a is None:
        return HTMLResponse("not found", status_code=404)
    name = name.strip().lower()
    if not name:
        return HTMLResponse("", status_code=400)
    tag = (await session.execute(select(Tag).where(Tag.name == name))).scalar_one_or_none()
    if tag is None:
        tag = Tag(name=name)
        session.add(tag)
        await session.flush()
    if tag in a.tags:
        a.tags.remove(tag)
        on = False
    else:
        a.tags.append(tag)
        on = True
    await session.commit()
    cls = "tag on" if on else "tag"
    return HTMLResponse(
        f'<span class="{cls}" hx-post="/articles/{aid}/tag" hx-vals=\'{{"name": "{tag.name}"}}\' hx-swap="outerHTML">{tag.name}</span>'
    )
