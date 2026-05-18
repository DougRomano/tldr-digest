from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from tldr.db.models import LLMProviderName


@dataclass(slots=True)
class ArticleSummary:
    summary: str
    so_what: str
    suggested_section: Optional[str] = None
    suggested_tags: list[str] = field(default_factory=list)
    badge_class: Optional[str] = None


@dataclass(slots=True)
class SectionCluster:
    emoji: str
    title: str
    article_ids: list[int]


@dataclass(slots=True)
class ReportTheme:
    headline: str
    eyebrow: str
    metrics: list[dict[str, str]]
    sections: list[SectionCluster]


class LLMProvider(ABC):
    name: LLMProviderName

    @abstractmethod
    async def summarize(self, *, title: str, snippet: str, source: str) -> ArticleSummary: ...

    @abstractmethod
    async def cluster_themes(self, articles: list[dict]) -> ReportTheme: ...

    @abstractmethod
    async def suggest_tags(self, *, title: str, snippet: str, existing: list[str]) -> list[str]: ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    @property
    @abstractmethod
    def chat_model(self) -> str: ...

    @property
    @abstractmethod
    def embed_model(self) -> str: ...


def _strip_json_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def parse_json_object(s: str) -> dict:
    s = _strip_json_fence(s)
    # Some models prepend chatter; isolate the first { ... } block.
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start : end + 1]
    return json.loads(s)
