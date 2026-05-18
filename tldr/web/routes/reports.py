from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tldr.db.models import LLMProviderName, Report, SourceName
from tldr.db.session import get_session
from tldr.reports.generator import generate_report
from tldr.web.templates import templates

router = APIRouter()


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(select(Report).order_by(Report.generated_at.desc()).limit(50))
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"active": "reports", "reports": rows, "sources": list(SourceName)},
    )


@router.post("/reports/generate", response_class=HTMLResponse)
async def reports_generate(
    request: Request,
    source: str = Form(...),
    provider: str = Form(""),
):
    src = SourceName(source)
    pv = LLMProviderName(provider) if provider else None
    try:
        stats = await generate_report(src, provider_override=pv)
    except RuntimeError as exc:
        return HTMLResponse(f'<div class="toast">{exc}</div>', status_code=400)
    return HTMLResponse(
        f'<div class="toast">wrote {stats.file_path.name} ({stats.article_count} articles)</div>'
        '<script>setTimeout(()=>location.reload(), 1200)</script>'
    )


@router.get("/reports/view/{rid}", response_class=HTMLResponse)
async def reports_view(rid: int, session: AsyncSession = Depends(get_session)):
    r = await session.get(Report, rid)
    if r is None:
        return HTMLResponse("not found", status_code=404)
    p = Path(r.file_path)
    if not p.exists():
        return HTMLResponse(f"file missing: {p}", status_code=410)
    return FileResponse(p, media_type="text/html")
