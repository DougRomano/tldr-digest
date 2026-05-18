from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from tldr.config import settings


class Base(DeclarativeBase):
    pass


class SourceName(str, enum.Enum):
    tldr_tech = "tldr_tech"
    tldr_ai = "tldr_ai"
    tldr_devops = "tldr_devops"
    tldr_dev = "tldr_dev"


class FetchStatus(str, enum.Enum):
    pending = "pending"
    parsed = "parsed"
    failed = "failed"


class EnrichStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    partial = "partial"
    failed = "failed"


class ReportStatus(str, enum.Enum):
    not_included = "not_included"
    included_in_report = "included_in_report"


class ArticleEnrichStatus(str, enum.Enum):
    pending = "pending"
    summarized = "summarized"
    embedded = "embedded"
    failed = "failed"


class LLMProviderName(str, enum.Enum):
    claude = "claude"
    ollama = "ollama"


# ---------------- M2M assoc ----------------

article_tag = Table(
    "article_tag",
    Base.metadata,
    Column("article_id", BigInteger, ForeignKey("article.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
)


# ---------------- Tables ----------------


class NewsletterIssue(Base):
    __tablename__ = "newsletter_issue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[SourceName] = mapped_column(Enum(SourceName, name="source_name"), index=True)
    subject: Mapped[str] = mapped_column(String(500))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    raw_html: Mapped[str] = mapped_column(Text)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    imap_uid: Mapped[str] = mapped_column(String(64))
    imap_folder: Mapped[str] = mapped_column(String(64), default="INBOX")

    fetch_status: Mapped[FetchStatus] = mapped_column(
        Enum(FetchStatus, name="fetch_status"), default=FetchStatus.pending, index=True
    )
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    parse_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    enrich_status: Mapped[EnrichStatus] = mapped_column(
        Enum(EnrichStatus, name="enrich_status"), default=EnrichStatus.pending, index=True
    )
    enriched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    enrich_provider: Mapped[Optional[LLMProviderName]] = mapped_column(
        Enum(LLMProviderName, name="llm_provider_name"), nullable=True
    )
    articles_extracted: Mapped[int] = mapped_column(Integer, default=0)
    articles_enriched: Mapped[int] = mapped_column(Integer, default=0)

    report_status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status"), default=ReportStatus.not_included, index=True
    )
    report_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("report.id", ondelete="SET NULL"), nullable=True
    )

    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    articles: Mapped[list["Article"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan"
    )
    report: Mapped[Optional["Report"]] = relationship(
        back_populates="issues", foreign_keys=[report_id]
    )

    __table_args__ = (
        UniqueConstraint("imap_uid", "imap_folder", name="uq_issue_imap_uid_folder"),
        Index("ix_issue_source_received", "source", "received_at"),
    )


class Article(Base):
    __tablename__ = "article"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("newsletter_issue.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(Text)
    raw_snippet: Mapped[str] = mapped_column(Text)
    read_time: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    # LLM-enriched
    llm_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_so_what: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_section: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    suggested_tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # CSV
    badge_class: Mapped[str] = mapped_column(String(20), default="b-general")

    enrich_status: Mapped[ArticleEnrichStatus] = mapped_column(
        Enum(ArticleEnrichStatus, name="article_enrich_status"),
        default=ArticleEnrichStatus.pending,
        index=True,
    )
    enrich_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enriched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped[NewsletterIssue] = relationship(back_populates="articles")
    tags: Mapped[list["Tag"]] = relationship(secondary=article_tag, back_populates="articles")
    embedding: Mapped[Optional["ArticleEmbedding"]] = relationship(
        back_populates="article", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_article_title_trgm", "title"),  # full-text added via migration
    )


class Tag(Base):
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    color: Mapped[str] = mapped_column(String(20), default="#94a3b8")

    articles: Mapped[list[Article]] = relationship(secondary=article_tag, back_populates="tags")


class ArticleEmbedding(Base):
    __tablename__ = "article_embedding"
    article_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("article.id", ondelete="CASCADE"), primary_key=True
    )
    vector: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim))
    model: Mapped[str] = mapped_column(String(80))
    provider: Mapped[LLMProviderName] = mapped_column(Enum(LLMProviderName, name="llm_provider_name"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    article: Mapped[Article] = relationship(back_populates="embedding")


class Report(Base):
    __tablename__ = "report"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[SourceName] = mapped_column(Enum(SourceName, name="source_name"))
    week_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    week_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    file_path: Mapped[str] = mapped_column(Text)
    headline: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    provider_used: Mapped[LLMProviderName] = mapped_column(
        Enum(LLMProviderName, name="llm_provider_name")
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issues: Mapped[list[NewsletterIssue]] = relationship(
        back_populates="report", foreign_keys=[NewsletterIssue.report_id]
    )


class AppSetting(Base):
    """Single-row settings table; key/value for runtime toggles like provider."""

    __tablename__ = "app_setting"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
