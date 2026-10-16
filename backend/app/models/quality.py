"""Foreshadowing and a lightweight per-novel word goal.

Conflict hints are not stored. They are computed and returned, never written back
into the manuscript or formal memory.
"""

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

from app.db.base import Base


class Foreshadowing(Base):
    __tablename__ = "foreshadowing"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'planned', 'resolved', 'abandoned', 'uncertain')",
            name="ck_foreshadowing_status",
        ),
        Index("ix_foreshadowing_novel_id", "novel_id"),
        Index("ix_foreshadowing_novel_id_status", "novel_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_foreshadowing_novel_id_novels"),
        nullable=False,
    )
    introduced_chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_foreshadowing_introduced_chapter_id_chapters"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payoff_chapter_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_foreshadowing_payoff_chapter_id_chapters"),
    )
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WritingGoal(Base):
    """Optional word-count target for one novel. It does not change chapter text."""

    __tablename__ = "writing_goals"
    __table_args__ = (
        UniqueConstraint("novel_id", name="uq_writing_goals_novel_id"),
        CheckConstraint("target_words >= 1", name="ck_writing_goals_target_words"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_writing_goals_novel_id_novels"),
        nullable=False,
    )
    target_words: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
