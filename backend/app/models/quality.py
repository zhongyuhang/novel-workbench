"""Foreshadowing, word goals, and evidence-backed quality issues.

Checks may store suspected issues and repair candidates. They do not rewrite
chapter text or formal memory. A candidate changes the manuscript only after
the author accepts it through the existing revision lock.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class QualityIssue(Base):
    """One suspected quality issue. Status is the author's, not an automatic edit."""

    __tablename__ = "quality_issues"
    __table_args__ = (
        UniqueConstraint("novel_id", "fingerprint", name="uq_quality_issues_novel_fingerprint"),
        CheckConstraint(
            "issue_type IN ("
            "'fact_continuity', 'time_continuity', 'character_continuity', "
            "'foreshadowing', 'outline_execution', 'text_surface'"
            ")",
            name="ck_quality_issues_issue_type",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_quality_issues_severity",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 100",
            name="ck_quality_issues_confidence",
        ),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'ignored', 'fixed', 'expired')",
            name="ck_quality_issues_status",
        ),
        CheckConstraint(
            "evidence_status IN ('sufficient', 'insufficient')",
            name="ck_quality_issues_evidence_status",
        ),
        CheckConstraint(
            "provider_mode IN ('rule', 'mock', 'openai_compatible')",
            name="ck_quality_issues_provider_mode",
        ),
        CheckConstraint("recheck_count >= 0", name="ck_quality_issues_recheck_count"),
        Index("ix_quality_issues_novel_id", "novel_id"),
        Index("ix_quality_issues_novel_id_status", "novel_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_quality_issues_novel_id_novels"),
        nullable=False,
    )
    chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_quality_issues_chapter_id_chapters"),
        nullable=False,
    )
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    manuscript_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    target_revision: Mapped[int | None] = mapped_column(Integer)
    location_note: Mapped[str | None] = mapped_column(Text)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    related_refs: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_version: Mapped[str | None] = mapped_column(String(64))
    provider_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    suggested_action: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fixed_revision: Mapped[int | None] = mapped_column(Integer)
    recheck_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QualityRepairCandidate(Base):
    """A suggested manuscript edit. ``proposed`` rows are not written into chapters."""

    __tablename__ = "quality_repair_candidates"
    __table_args__ = (
        CheckConstraint(
            "apply_mode IN ('replace_selection', 'append')",
            name="ck_quality_repair_candidates_apply_mode",
        ),
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'rejected', 'conflict')",
            name="ck_quality_repair_candidates_status",
        ),
        CheckConstraint(
            "provider_mode IN ('rule', 'mock', 'openai_compatible')",
            name="ck_quality_repair_candidates_provider_mode",
        ),
        CheckConstraint(
            "target_revision >= 1", name="ck_quality_repair_candidates_target_revision"
        ),
        Index("ix_quality_repair_candidates_issue_id", "issue_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issue_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "quality_issues.id", name="fk_quality_repair_candidates_issue_id_quality_issues"
        ),
        nullable=False,
    )
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_quality_repair_candidates_novel_id_novels"),
        nullable=False,
    )
    chapter_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_quality_repair_candidates_chapter_id_chapters"),
        nullable=False,
    )
    target_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    apply_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    applicable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    original_snippet: Mapped[str] = mapped_column(Text, nullable=False)
    replacement_text: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    diff_preview: Mapped[str] = mapped_column(Text, nullable=False)
    provider_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
