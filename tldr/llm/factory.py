from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tldr.config import settings
from tldr.db.models import AppSetting, LLMProviderName
from tldr.llm.base import LLMProvider
from tldr.llm.claude import ClaudeProvider
from tldr.llm.ollama import OllamaProvider

log = logging.getLogger(__name__)


async def _read_settings(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(AppSetting))).scalars().all()
    return {r.key: r.value for r in rows}


def _coerce_provider(value: str | None) -> LLMProviderName:
    try:
        return LLMProviderName(value) if value else LLMProviderName(settings.default_llm_provider)
    except ValueError:
        return LLMProviderName(settings.default_llm_provider)


async def get_active_provider_name(session: AsyncSession) -> LLMProviderName:
    rows = await _read_settings(session)
    return _coerce_provider(rows.get("active_provider"))


def make_provider(name: LLMProviderName) -> LLMProvider:
    """Build a provider from .env defaults only (no DB). For CLI/doctor use."""
    if name == LLMProviderName.claude:
        return ClaudeProvider()
    if name == LLMProviderName.ollama:
        return OllamaProvider()
    raise ValueError(f"unknown provider: {name}")


async def get_provider(
    session: AsyncSession, override: LLMProviderName | None = None
) -> LLMProvider:
    """Build the active provider, with model names resolved from the
    app_setting table (set via the web Settings page) and .env as fallback.
    """
    rows = await _read_settings(session)
    name = override or _coerce_provider(rows.get("active_provider"))
    if name == LLMProviderName.claude:
        return ClaudeProvider(chat_model=rows.get("claude_model") or settings.claude_model)
    if name == LLMProviderName.ollama:
        return OllamaProvider(
            chat_model=rows.get("ollama_chat_model") or settings.ollama_chat_model,
            embed_model=rows.get("ollama_embed_model") or settings.ollama_embed_model,
        )
    raise ValueError(f"unknown provider: {name}")
