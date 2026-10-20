"""Model configuration and AI task tables."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


class ModelConfig(Base):
    """Stored model endpoint. The API key lives only as ciphertext in secret_ref."""

    __tablename__ = "model_configs"
    __table_args__ = (
        CheckConstraint(
            "provider_type IN ('openai_compatible', 'mock')",
            name="ck_model_configs_provider_type",
        ),
        CheckConstraint(
            "last_test_status IN ('untested', 'success', 'failed', 'stale')",
            name="ck_model_configs_last_test_status",
        ),
        Index("ix_model_configs_is_enabled", "is_enabled"),
        Index(
            "uq_model_configs_one_default",
            "is_default",
            unique=True,
            sqlite_where=text("is_default = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    secret_ref: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    encrypted_custom_headers: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    capabilities: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_test_status: Mapped[str] = mapped_column(String(32), nullable=False, default="untested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AiTask(Base):
    """One generation. completed means a candidate is ready, not that the chapter changed."""

    __tablename__ = "ai_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_ai_tasks_status",
        ),
        CheckConstraint(
            "task_type IN ('continue', 'rewrite', 'polish', 'expand', 'shrink', 'proofread')",
            name="ck_ai_tasks_task_type",
        ),
        CheckConstraint(
            "resolution IS NULL OR resolution IN ('accepted', 'rejected')",
            name="ck_ai_tasks_resolution",
        ),
        Index("ix_ai_tasks_novel_id", "novel_id"),
        Index("ix_ai_tasks_chapter_id", "chapter_id"),
        Index("ix_ai_tasks_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    novel_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("novels.id", name="fk_ai_tasks_novel_id_novels"),
        nullable=False,
    )
    chapter_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chapters.id", name="fk_ai_tasks_chapter_id_chapters"),
    )
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    model_config_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "model_configs.id",
            name="fk_ai_tasks_model_config_id_model_configs",
            ondelete="SET NULL",
        ),
    )
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    output_text: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message_safe: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    resolution: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
