"""ORM models registered for Alembic metadata."""

from app.db.base import Base
from app.models.ai import AiTask, ModelConfig
from app.models.catalog import Chapter, ChapterVersion, Novel, Volume
from app.models.chronicle import ChronicleCandidate
from app.models.ideation import IdeationCandidate, IdeationSession
from app.models.memory import (
    ChapterSummary,
    EntityRelation,
    EntityState,
    MemoryChangeProposal,
    StoryEntity,
    StoryEvent,
)
from app.models.planning import ChapterOutline, SceneCard, StoryArc, StoryPlan, VolumeOutline
from app.models.quality import Foreshadowing, QualityIssue, QualityRepairCandidate, WritingGoal

__all__ = [
    "AiTask",
    "Base",
    "Chapter",
    "ChapterOutline",
    "ChronicleCandidate",
    "ChapterSummary",
    "ChapterVersion",
    "EntityRelation",
    "EntityState",
    "Foreshadowing",
    "IdeationCandidate",
    "IdeationSession",
    "QualityIssue",
    "QualityRepairCandidate",
    "MemoryChangeProposal",
    "ModelConfig",
    "Novel",
    "SceneCard",
    "StoryArc",
    "StoryEntity",
    "StoryEvent",
    "StoryPlan",
    "Volume",
    "VolumeOutline",
    "WritingGoal",
]
