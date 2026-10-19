"""ORM models registered for Alembic metadata."""

from app.db.base import Base
from app.models.ai import AiTask, ModelConfig
from app.models.catalog import Chapter, ChapterVersion, Novel, Volume
from app.models.memory import (
    ChapterSummary,
    EntityRelation,
    EntityState,
    MemoryChangeProposal,
    StoryEntity,
    StoryEvent,
)
from app.models.planning import ChapterOutline, SceneCard, StoryPlan
from app.models.quality import Foreshadowing, QualityIssue, QualityRepairCandidate, WritingGoal

__all__ = [
    "AiTask",
    "Base",
    "Chapter",
    "ChapterOutline",
    "ChapterSummary",
    "ChapterVersion",
    "EntityRelation",
    "EntityState",
    "Foreshadowing",
    "QualityIssue",
    "QualityRepairCandidate",
    "MemoryChangeProposal",
    "ModelConfig",
    "Novel",
    "SceneCard",
    "StoryEntity",
    "StoryEvent",
    "StoryPlan",
    "Volume",
    "WritingGoal",
]
