from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tldr.config import settings
from tldr.db.models import (
    Article,
    ArticleEnrichStatus,
    EnrichStatus,
    LLMProviderName,
    NewsletterIssue,
    Report,
    ReportStatus,
    SourceName,
)
from tldr.db.session import session_scope
from tldr.llm.factory import get_provider

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"

SOURCE_DISPLAY = {
    SourceName.tldr_tech: "TLDR Tech",
    SourceName.tldr_ai: "TLDR AI",
    SourceName.tldr_devops: "TLDR DevOps",
    SourceName.tldr_dev: "TLDR Dev",
}
BADGE_LABEL = {
    SourceName.tldr_tech: "TLDR",
    SourceName.tldr_ai: "TLDR AI",
    SourceName.tldr_devops: "TLDR DevOps",
    SourceName.tldr_dev: "TLDR Dev",
}
SOURCE_ACCENT = {
    SourceName.tldr_tech: ("#a78bfa", "rgba(167, 139, 250, 0.06)", "#c4b5fd"),
    SourceName.tldr_ai: ("#60a5fa", "rgba(96, 165, 250, 0.06)", "#93c5fd"),
    SourceName.tldr_devops: ("#fb923c", "rgba(251, 146, 60, 0.06)", "#fdba74"),
    SourceName.tldr_dev: ("#34d399", "rgba(52, 211, 153, 0.06)", "#6ee7b7"),
}
SOURCE_FILE_PREFIX = {
    SourceName.tldr_tech: "TLDR_Tech",
    SourceName.tldr_ai: "TLDR_AI",
    SourceName.tldr_devops: "TLDR_DevOps",
    SourceName.tldr_dev: "TLDR_Dev",
}


@dataclass(slots=True)
class GenStats:
    file_path: Path
    article_count: int
    issue_count: int


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _week_range(reference: datetime | None = None) -> tuple[datetime, datetime]:
    now = reference or datetime.now(timezone.utc)
    start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return start, end


def _card_dict(a: Article, source: SourceName) -> dict:
    tags = []
    if a.suggested_tags:
        tags = [t.strip() for t in a.suggested_tags.split(",") if t.strip()]
    received = a.issue.received_at.strftime("%b %d")
    return {
        "id": a.id,
        "url": a.url,
        "title": a.title,
        "badge_class": a.badge_class,
        "badge_label": BADGE_LABEL[source],
        "summary": a.llm_summary or a.raw_snippet[:600],
        "so_what": a.llm_so_what or "",
        "tags": tags[:5],
        "meta": f"{SOURCE_DISPLAY[source]} · {received}",
    }


async def generate_report(
    source: SourceName,
    *,
    provider_override: LLMProviderName | None = None,
    reference: datetime | None = None,
) -> GenStats:
    start, end = _week_range(reference)
    async with session_scope() as s:
        provider = await get_provider(s, override=provider_override)

        issues = (
            await s.execute(
                select(NewsletterIssue)
                .where(
                    NewsletterIssue.source == source,
                    NewsletterIssue.received_at >= start,
                    NewsletterIssue.received_at <= end,
                )
                .options(selectinload(NewsletterIssue.articles))
                .order_by(NewsletterIssue.received_at)
            )
        ).scalars().all()
        articles: list[Article] = []
        for issue in issues:
            for a in issue.articles:
                if a.enrich_status in (ArticleEnrichStatus.summarized, ArticleEnrichStatus.embedded):
                    articles.append(a)

        if not articles:
            raise RuntimeError(
                f"no enriched articles for {source.value} in {start.date()}..{end.date()} — "
                "run `tldr fetch` and `tldr enrich` first."
            )

        # Cluster via LLM
        articles_payload = [
            {
                "id": a.id,
                "title": a.title,
                "summary": a.llm_summary or a.raw_snippet[:200],
                "source_display": SOURCE_DISPLAY[source],
                "week_display": f"{start.strftime('%b %-d')}–{end.strftime('%b %-d, %Y')}",
            }
            for a in articles
        ]
        theme = await provider.cluster_themes(articles_payload)

        # Build sections (map article_id → card)
        article_by_id = {a.id: a for a in articles}
        sections = []
        assigned: set[int] = set()
        for sec in theme.sections:
            cards = []
            for aid in sec.article_ids:
                a = article_by_id.get(aid)
                if a is None or aid in assigned:
                    continue
                cards.append(_card_dict(a, source))
                assigned.add(aid)
            if cards:
                sections.append({"emoji": sec.emoji, "title": sec.title, "cards": cards})

        # Sweep any article the LLM forgot into a "More from this week" section
        leftovers = [a for a in articles if a.id not in assigned]
        if leftovers:
            sections.append(
                {
                    "emoji": "📰",
                    "title": "More from this week",
                    "cards": [_card_dict(a, source) for a in leftovers],
                }
            )

        # Bonus .NET / Azure pull-aside — articles tagged azure or dotnet or with .NET in summary
        bonus_cards = []
        for a in articles:
            tag_str = (a.suggested_tags or "").lower()
            blob = f"{a.llm_summary or ''} {a.llm_so_what or ''} {a.raw_snippet or ''}".lower()
            if (
                "azure" in tag_str
                or "dotnet" in tag_str
                or ".net" in blob
                or " azure " in f" {blob} "
            ):
                bonus_cards.append(_card_dict(a, source))
        bonus_section = {"cards": bonus_cards[:4]} if bonus_cards else None

        accent, so_what_bg, so_what_strong = SOURCE_ACCENT[source]
        now = reference or datetime.now(timezone.utc)
        ctx = {
            "source_display": SOURCE_DISPLAY[source],
            "eyebrow": theme.eyebrow or f"Weekly TLDR Digest — Topic: {SOURCE_DISPLAY[source]}",
            "headline": theme.headline or f"This week in {SOURCE_DISPLAY[source]}",
            "date_range": f"{start.strftime('%b %-d')}–{end.strftime('%b %-d, %Y')}",
            "generated_date": now.strftime("%B %-d, %Y"),
            "accent_color": accent,
            "so_what_bg": so_what_bg,
            "so_what_strong": so_what_strong,
            "stats": {
                "newsletters_scanned": len(issues),
                "articles_count": len(articles),
                "date_range_short": f"{start.strftime('%b %-d')}–{end.strftime('%-d')}",
                "sources_display": SOURCE_DISPLAY[source],
            },
            "metrics": theme.metrics[:4],
            "sections": sections,
            "bonus_section": bonus_section,
        }

        template = _env().get_template("report.html.j2")
        html = template.render(**ctx)

        out_dir = settings.reports_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{SOURCE_FILE_PREFIX[source]}_TLDR_{now.strftime('%Y-%m-%d')}.html"
        out_path = out_dir / filename
        out_path.write_text(html, encoding="utf-8")

        # Persist Report row + back-link issues
        report = Report(
            source=source,
            week_start=start,
            week_end=end,
            file_path=str(out_path),
            headline=theme.headline,
            provider_used=provider.name,
        )
        s.add(report)
        await s.flush()
        for issue in issues:
            issue.report_id = report.id
            issue.report_status = ReportStatus.included_in_report
            # If at least one of its articles ended up in the report, the issue counts
            if issue.enrich_status == EnrichStatus.pending:
                issue.enrich_status = EnrichStatus.partial

        return GenStats(file_path=out_path, article_count=len(articles), issue_count=len(issues))
