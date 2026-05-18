from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from tldr.db.models import Article, ArticleEmbedding
from tldr.db.session import get_session
from tldr.llm.factory import get_provider
from tldr.web.templates import templates

router = APIRouter()


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: Optional[str] = None,
    mode: str = "hybrid",
    session: AsyncSession = Depends(get_session),
):
    results: list[dict] = []
    if q:
        results = await _run_search(session, q, mode)
    return templates.TemplateResponse(
        request,
        "search.html",
        {"active": "search", "q": q or "", "mode": mode, "results": results},
    )


async def _run_search(session: AsyncSession, q: str, mode: str) -> list[dict]:
    fts_rows: dict[int, tuple[float, Article]] = {}
    vec_rows: dict[int, tuple[float, Article]] = {}

    if mode in ("fts", "hybrid"):
        # plainto_tsquery is robust against punctuation; ts_rank for scoring.
        sql = text(
            """
            SELECT id, ts_rank(to_tsvector('english',
                       coalesce(title,'') || ' ' || coalesce(raw_snippet,'') || ' ' || coalesce(llm_summary,'')),
                       plainto_tsquery('english', :q)) AS rank
            FROM article
            WHERE to_tsvector('english',
                       coalesce(title,'') || ' ' || coalesce(raw_snippet,'') || ' ' || coalesce(llm_summary,''))
                  @@ plainto_tsquery('english', :q)
            ORDER BY rank DESC LIMIT 30
            """
        )
        rows = (await session.execute(sql, {"q": q})).all()
        if rows:
            ids = [r.id for r in rows]
            arts = (
                await session.execute(
                    select(Article).where(Article.id.in_(ids)).options(selectinload(Article.issue))
                )
            ).scalars().all()
            by_id = {a.id: a for a in arts}
            for rank, r in enumerate(rows):
                a = by_id.get(r.id)
                if a:
                    fts_rows[a.id] = (rank, a)

    if mode in ("semantic", "hybrid"):
        provider = await get_provider(session)
        vec = await provider.embed(q)
        stmt = (
            select(Article, ArticleEmbedding.vector.cosine_distance(vec).label("dist"))
            .join(ArticleEmbedding, ArticleEmbedding.article_id == Article.id)
            .order_by("dist")
            .limit(30)
            .options(selectinload(Article.issue))
        )
        rows2 = (await session.execute(stmt)).all()
        for rank, (a, _dist) in enumerate(rows2):
            vec_rows[a.id] = (rank, a)

    # Reciprocal Rank Fusion
    k = 60
    scored: dict[int, tuple[float, Article]] = {}
    for aid, (rank, a) in fts_rows.items():
        scored[aid] = (scored.get(aid, (0.0, a))[0] + 1.0 / (k + rank + 1), a)
    for aid, (rank, a) in vec_rows.items():
        scored[aid] = (scored.get(aid, (0.0, a))[0] + 1.0 / (k + rank + 1), a)

    ordered = sorted(scored.values(), key=lambda x: -x[0])[:25]
    return [
        {
            "article": a,
            "score": round(score, 4),
            "in_fts": a.id in fts_rows,
            "in_semantic": a.id in vec_rows,
        }
        for score, a in ordered
    ]
