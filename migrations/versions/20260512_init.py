"""init schema

Revision ID: 0001_init
Revises:
Create Date: 2026-05-12

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SOURCE_NAME = ("tldr_tech", "tldr_ai", "tldr_devops", "tldr_dev")
FETCH_STATUS = ("pending", "parsed", "failed")
ENRICH_STATUS = ("pending", "in_progress", "completed", "partial", "failed")
REPORT_STATUS = ("not_included", "included_in_report")
ARTICLE_ENRICH_STATUS = ("pending", "summarized", "embedded", "failed")
LLM_PROVIDER_NAME = ("claude", "ollama")

EMBEDDING_DIM = 1024


def upgrade() -> None:
    # extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # enums — create each Postgres type ONCE here via raw SQL, then reference
    # them in columns with create_type=False so create_table() never re-emits
    # CREATE TYPE (multiple tables share the same types).
    def _mkenum(name: str, values: tuple[str, ...]) -> None:
        vals = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({vals})")

    _mkenum("source_name", SOURCE_NAME)
    _mkenum("fetch_status", FETCH_STATUS)
    _mkenum("enrich_status", ENRICH_STATUS)
    _mkenum("report_status", REPORT_STATUS)
    _mkenum("article_enrich_status", ARTICLE_ENRICH_STATUS)
    _mkenum("llm_provider_name", LLM_PROVIDER_NAME)

    source_enum = postgresql.ENUM(*SOURCE_NAME, name="source_name", create_type=False)
    fetch_enum = postgresql.ENUM(*FETCH_STATUS, name="fetch_status", create_type=False)
    enrich_enum = postgresql.ENUM(*ENRICH_STATUS, name="enrich_status", create_type=False)
    report_enum = postgresql.ENUM(*REPORT_STATUS, name="report_status", create_type=False)
    article_enrich_enum = postgresql.ENUM(
        *ARTICLE_ENRICH_STATUS, name="article_enrich_status", create_type=False
    )
    provider_enum = postgresql.ENUM(*LLM_PROVIDER_NAME, name="llm_provider_name", create_type=False)

    # report — created first so newsletter_issue.report_id can FK it
    op.create_table(
        "report",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", source_enum, nullable=False),
        sa.Column("week_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("week_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("headline", sa.String(500)),
        sa.Column("provider_used", provider_enum, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "newsletter_issue",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", source_enum, nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_html", sa.Text, nullable=False),
        sa.Column("raw_text", sa.Text),
        sa.Column("imap_uid", sa.String(64), nullable=False),
        sa.Column("imap_folder", sa.String(64), nullable=False, server_default="INBOX"),
        sa.Column("fetch_status", fetch_enum, nullable=False, server_default="pending"),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("parse_error", sa.Text),
        sa.Column("enrich_status", enrich_enum, nullable=False, server_default="pending"),
        sa.Column("enriched_at", sa.DateTime(timezone=True)),
        sa.Column("enrich_provider", provider_enum),
        sa.Column("articles_extracted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("articles_enriched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("report_status", report_enum, nullable=False, server_default="not_included"),
        sa.Column(
            "report_id",
            sa.BigInteger,
            sa.ForeignKey("report.id", ondelete="SET NULL"),
        ),
        sa.Column("reviewed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("imap_uid", "imap_folder", name="uq_issue_imap_uid_folder"),
    )
    op.create_index("ix_issue_source_received", "newsletter_issue", ["source", "received_at"])
    op.create_index("ix_issue_source", "newsletter_issue", ["source"])
    op.create_index("ix_issue_received_at", "newsletter_issue", ["received_at"])
    op.create_index("ix_issue_fetch_status", "newsletter_issue", ["fetch_status"])
    op.create_index("ix_issue_enrich_status", "newsletter_issue", ["enrich_status"])
    op.create_index("ix_issue_report_status", "newsletter_issue", ["report_status"])
    op.create_index("ix_issue_reviewed", "newsletter_issue", ["reviewed"])

    op.create_table(
        "article",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "issue_id",
            sa.BigInteger,
            sa.ForeignKey("newsletter_issue.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("raw_snippet", sa.Text, nullable=False),
        sa.Column("read_time", sa.String(40)),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("llm_summary", sa.Text),
        sa.Column("llm_so_what", sa.Text),
        sa.Column("suggested_section", sa.String(120)),
        sa.Column("suggested_tags", sa.Text),
        sa.Column("badge_class", sa.String(20), nullable=False, server_default="b-general"),
        sa.Column("enrich_status", article_enrich_enum, nullable=False, server_default="pending"),
        sa.Column("enrich_error", sa.Text),
        sa.Column("enriched_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_article_issue_id", "article", ["issue_id"])
    op.create_index("ix_article_enrich_status", "article", ["enrich_status"])
    op.create_index("ix_article_reviewed", "article", ["reviewed"])

    # full-text search on title + raw_snippet (immutable expression index)
    op.execute(
        "CREATE INDEX ix_article_fts ON article USING GIN ("
        "to_tsvector('english', coalesce(title,'') || ' ' || coalesce(raw_snippet,'') || ' ' || coalesce(llm_summary,'')))"
    )
    # trigram index on title for fuzzy search
    op.execute("CREATE INDEX ix_article_title_trgm ON article USING GIN (title gin_trgm_ops)")

    op.create_table(
        "tag",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
        sa.Column("color", sa.String(20), nullable=False, server_default="#94a3b8"),
    )

    op.create_table(
        "article_tag",
        sa.Column(
            "article_id",
            sa.BigInteger,
            sa.ForeignKey("article.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Integer,
            sa.ForeignKey("tag.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "article_embedding",
        sa.Column(
            "article_id",
            sa.BigInteger,
            sa.ForeignKey("article.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("vector", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("provider", provider_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute(
        f"CREATE INDEX ix_article_embedding_vec ON article_embedding USING ivfflat (vector vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # seed default tags
    seed_tags = [
        ("mcp", "#2dd4bf"),
        ("azure", "#60a5fa"),
        ("dotnet", "#a78bfa"),
        ("claude", "#fb923c"),
        ("cursor", "#34d399"),
        ("ai-agents", "#f472b6"),
        ("security", "#f87171"),
        ("observability", "#fbbf24"),
        ("devops", "#fb923c"),
        ("blog-fodder", "#c084fc"),
    ]
    op.bulk_insert(
        sa.table("tag", sa.column("name", sa.String), sa.column("color", sa.String)),
        [{"name": n, "color": c} for n, c in seed_tags],
    )

    # seed default settings
    op.bulk_insert(
        sa.table("app_setting", sa.column("key", sa.String), sa.column("value", sa.Text)),
        [
            {"key": "active_provider", "value": "claude"},
            {"key": "claude_model", "value": "claude-sonnet-4-6"},
            {"key": "ollama_chat_model", "value": "llama3.1:8b"},
            {"key": "ollama_embed_model", "value": "mxbai-embed-large"},
        ],
    )


def downgrade() -> None:
    op.drop_table("app_setting")
    op.execute("DROP INDEX IF EXISTS ix_article_embedding_vec")
    op.drop_table("article_embedding")
    op.drop_table("article_tag")
    op.drop_table("tag")
    op.execute("DROP INDEX IF EXISTS ix_article_fts")
    op.execute("DROP INDEX IF EXISTS ix_article_title_trgm")
    op.drop_table("article")
    op.drop_table("newsletter_issue")
    op.drop_table("report")
    for name in (
        "article_enrich_status",
        "report_status",
        "enrich_status",
        "fetch_status",
        "source_name",
        "llm_provider_name",
    ):
        op.execute(f"DROP TYPE IF EXISTS {name}")
