from __future__ import annotations

import logging
from typing import Optional

import httpx
import ollama

from tldr.config import settings
from tldr.db.models import LLMProviderName
from tldr.llm.base import ArticleSummary, LLMProvider, ReportTheme, SectionCluster, parse_json_object
from tldr.llm.prompts import (
    SUMMARIZE_SYSTEM,
    SUMMARIZE_USER,
    TAG_SYSTEM,
    TAG_USER,
    THEME_SYSTEM,
    THEME_USER,
)

log = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    name = LLMProviderName.ollama

    def __init__(
        self,
        host: Optional[str] = None,
        chat_model: Optional[str] = None,
        embed_model: Optional[str] = None,
    ):
        self._host = host or settings.ollama_host
        self._chat_model = chat_model or settings.ollama_chat_model
        self._embed_model = embed_model or settings.ollama_embed_model
        self._client = ollama.AsyncClient(host=self._host)

    @property
    def chat_model(self) -> str:
        return self._chat_model

    @property
    def embed_model(self) -> str:
        return self._embed_model

    async def _chat_json(self, *, system: str, user: str, num_predict: int = 1200) -> dict:
        resp = await self._client.chat(
            model=self._chat_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            format="json",
            options={"temperature": 0.2, "num_predict": num_predict},
        )
        content = resp["message"]["content"]
        return parse_json_object(content)

    async def summarize(self, *, title: str, snippet: str, source: str) -> ArticleSummary:
        data = await self._chat_json(
            system=SUMMARIZE_SYSTEM,
            user=SUMMARIZE_USER.format(source=source, title=title, snippet=snippet[:3000]),
        )
        return ArticleSummary(
            summary=str(data.get("summary", "")).strip(),
            so_what=str(data.get("so_what", "")).strip(),
            suggested_section=str(data.get("suggested_section", "")).strip() or None,
            suggested_tags=[str(t).strip().lower() for t in data.get("suggested_tags", []) if t],
        )

    async def cluster_themes(self, articles: list[dict]) -> ReportTheme:
        listing = "\n".join(
            f"- id={a['id']} | {a['title']} | {a.get('summary') or a.get('snippet','')[:160]}"
            for a in articles
        )
        data = await self._chat_json(
            system=THEME_SYSTEM,
            user=THEME_USER.format(
                source_display=articles[0].get("source_display", "TLDR"),
                week_display=articles[0].get("week_display", ""),
                article_list=listing,
            ),
            num_predict=2200,
        )
        return ReportTheme(
            headline=str(data.get("headline", "")).strip(),
            eyebrow=str(data.get("eyebrow", "")).strip(),
            metrics=[{k: str(v) for k, v in m.items()} for m in data.get("metrics", [])],
            sections=[
                SectionCluster(
                    emoji=str(s.get("emoji", "")).strip() or "📰",
                    title=str(s.get("title", "")).strip(),
                    article_ids=[int(x) for x in s.get("article_ids", []) if str(x).strip().isdigit()],
                )
                for s in data.get("sections", [])
            ],
        )

    async def suggest_tags(self, *, title: str, snippet: str, existing: list[str]) -> list[str]:
        resp = await self._client.chat(
            model=self._chat_model,
            messages=[
                {"role": "system", "content": TAG_SYSTEM},
                {"role": "user", "content": TAG_USER.format(existing=", ".join(existing), title=title, snippet=snippet[:1500])},
            ],
            format="json",
            options={"temperature": 0.2, "num_predict": 200},
        )
        text = resp["message"]["content"].strip()
        try:
            import json
            arr = json.loads(text)
            if isinstance(arr, list):
                return [str(t).strip().lower() for t in arr if str(t).strip()][:5]
            if isinstance(arr, dict) and "tags" in arr:
                return [str(t).strip().lower() for t in arr["tags"] if str(t).strip()][:5]
        except json.JSONDecodeError:
            pass
        return []

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{self._host.rstrip('/')}/api/embeddings",
                json={"model": self._embed_model, "prompt": text[:8000]},
            )
            r.raise_for_status()
            vec = r.json()["embedding"]
        # Right-pad or truncate to the schema's fixed dim.
        target = settings.embedding_dim
        if len(vec) < target:
            vec = vec + [0.0] * (target - len(vec))
        elif len(vec) > target:
            vec = vec[:target]
        return vec
