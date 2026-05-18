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


async def get_active_provider_name(session: AsyncSession) -> LLMProviderName:
    row = await session.scalar(select(AppSetting).where(AppSetting.key == "active_provider"))
    if row is None:
        return LLMProviderName(settings.default_llm_provider)
    try:
        return LLMProviderName(row.value)
    except ValueError:
        return LLMProviderName(settings.default_llm_provider)


def make_provider(name: LLMProviderName) -> LLMProvider:
    if name == LLMProviderName.claude:
        return ClaudeProvider()
    if name == LLMProviderName.ollama:
        return OllamaProvider()
    raise ValueError(f"unknown provider: {name}")


async def get_provider(session: AsyncSession, override: LLMProviderName | None = None) -> LLMProvider:
    name = override or await get_active_provider_name(session)
    return make_provider(name)
