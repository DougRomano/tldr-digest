from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tldr.config import settings as app_settings
from tldr.db.models import AppSetting, LLMProviderName
from tldr.db.session import get_session
from tldr.web.templates import templates

router = APIRouter()

KEYS = ("active_provider", "claude_model", "ollama_chat_model", "ollama_embed_model")


async def _read_all(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(AppSetting).where(AppSetting.key.in_(KEYS)))).scalars().all()
    return {r.key: r.value for r in rows}


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, session: AsyncSession = Depends(get_session)):
    cur = await _read_all(session)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active": "settings",
            "cur": cur,
            "providers": [p.value for p in LLMProviderName],
            "anthropic_key_set": bool(app_settings.anthropic_api_key),
            "ollama_host": app_settings.ollama_host,
            "yahoo_user": app_settings.yahoo_user,
            "yahoo_pw_set": bool(app_settings.yahoo_app_password),
            "db_url": app_settings.database_url,
            "reports_dir": str(app_settings.reports_dir),
        },
    )


@router.post("/settings")
async def settings_save(
    request: Request,
    active_provider: str = Form(...),
    claude_model: str = Form(""),
    ollama_chat_model: str = Form(""),
    ollama_embed_model: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    pairs = {
        "active_provider": active_provider,
        "claude_model": claude_model,
        "ollama_chat_model": ollama_chat_model,
        "ollama_embed_model": ollama_embed_model,
    }
    for k, v in pairs.items():
        if not v:
            continue
        existing = await session.get(AppSetting, k)
        if existing is None:
            session.add(AppSetting(key=k, value=v))
        else:
            existing.value = v
    await session.commit()
    return RedirectResponse(url="/settings", status_code=303)
