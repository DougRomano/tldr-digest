from __future__ import annotations

import logging
from typing import Optional

import httpx
from anthropic import AsyncAnthropic

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


class ClaudeProvider(LLMProvider):
    name = LLMProviderName.claude

    def __init__(self, api_key: Optional[str] = None, chat_model: Optional[str] = None):
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        self._client = AsyncAnthropic(api_key=key)
        self._chat_model = chat_model or settings.claude_model
        # Embeddings: Anthropic doesn't ship an embedding endpoint; use Voyage
        # (Anthropic's recommended embedding provider) if a VOYAGE_API_KEY is set
        # in the environment, else fall back to a deterministic local hash embedding
        # so the pipeline still completes end-to-end.
        import os

        self._voyage_key = os.environ.get("VOYAGE_API_KEY", "").strip()
        self._embed_model_name = settings.claude_embed_model

    @property
    def chat_model(self) -> str:
        return self._chat_model

    @property
    def embed_model(self) -> str:
        return self._embed_model_name if self._voyage_key else "fallback-hash-1024"

    async def _chat_json(self, *, system: str, user: str, max_tokens: int = 1200) -> dict:
        resp = await self._client.messages.create(
            model=self._chat_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return parse_json_object(text)

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
            max_tokens=2200,
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
        resp = await self._client.messages.create(
            model=self._chat_model,
            max_tokens=200,
            system=TAG_SYSTEM,
            messages=[{"role": "user", "content": TAG_USER.format(existing=", ".join(existing), title=title, snippet=snippet[:1500])}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        try:
            import json
            arr = json.loads(text)
            return [str(t).strip().lower() for t in arr if str(t).strip()][:5]
        except json.JSONDecodeError:
            return []

    async def embed(self, text: str) -> list[float]:
        if self._voyage_key:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    "https://api.voyageai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self._voyage_key}"},
                    json={"input": [text[:8000]], "model": self._embed_model_name, "output_dimension": settings.embedding_dim},
                )
                r.raise_for_status()
                return r.json()["data"][0]["embedding"]
        # Fallback so the pipeline still completes when Voyage is not configured.
        return _hash_embedding(text, settings.embedding_dim)


def _hash_embedding(text: str, dim: int) -> list[float]:
    """Deterministic, fast pseudo-embedding so semantic-search code can run
    end-to-end without a real embedding API. NOT semantically meaningful —
    swap to Voyage or sentence-transformers for real similarity.
    """
    import hashlib
    import math

    # blake2b caps digest_size at 64 bytes, so collect `dim` bytes across
    # multiple salted hashes of the same input.
    data = text.encode("utf-8")
    buf = bytearray()
    counter = 0
    while len(buf) < dim:
        buf.extend(
            hashlib.blake2b(data, digest_size=64, salt=counter.to_bytes(2, "little")).digest()
        )
        counter += 1
    vec = [((b - 127.5) / 127.5) for b in buf[:dim]]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]
