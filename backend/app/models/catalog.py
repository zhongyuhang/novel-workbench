"""Novel, volume, and chapter tables."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


class Novel(Base):
    __tablename__ = "novels"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_novels_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    genre: Mapped[str | None] = mapped_column(String(100))
    synopsis: Mapped[str | None] = mapped_column(Text)
    style_guide: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Volume(Base):
    __tablename__ = "volumes"
    __table_args__ = (Index("ix_volumes_novel_id_sort_order", "novel_id", "sort_order"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_volumes_novel_id_novels"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        Index("ix_chapters_novel_id_sort_order", "novel_id", "sort_order"),
        Index("ix_chapters_volume_id_sort_order", "volume_id", "sort_order"),
        CheckConstraint(
            "status IN ('outline', 'draft', 'revised', 'final')",
            name="ck_chapters_status",
        ),
        CheckConstraint("content_format = 'tiptap_json'", name="ck_chapters_content_format"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_chapters_novel_id_novels"),
        nullable=False,
    )
    volume_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("volumes.id", name="fk_chapters_volume_id_volumes", ondelete="SET NULL"),
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    content_format: Mapped[str] = mapped_column(String(32), nullable=False)
    content_format_version: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChapterVersion(Base):
    """Content snapshot for one chapter revision.

    Rows are written for manual saves, accepted AI candidates, restores, and imports.
    Autosave updates ``chapters`` only.
    """

    __tablename__ = "chapter_versions"
    __table_args__ = (
        UniqueConstraint(
            "chapter_id",
            "revision",
            name="uq_chapter_versions_chapter_id_revision",
        ),
        CheckConstraint(
            "change_source IN ('manual', 'ai_accepted', 'restore', 'import')",
            name="ck_chapter_versions_change_source",
        ),
        CheckConstraint(
            "content_format = 'tiptap_json'",
            name="ck_chapter_versions_content_format",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_chapter_versions_chapter_id_chapters"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    content_format: Mapped[str] = mapped_column(String(32), nullable=False)
    content_format_version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_source: Mapped[str] = mapped_column(String(32), nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text)
    ai_task_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "ai_tasks.id",
            name="fk_chapter_versions_ai_task_id_ai_tasks",
            ondelete="SET NULL",
        ),
    )
    repair_candidate_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "quality_repair_candidates.id",
            name="fk_chapter_versions_repair_candidate_id_quality_repair_candidates",
            ondelete="SET NULL",
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
