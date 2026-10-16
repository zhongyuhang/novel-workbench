"""ORM models registered for Alembic metadata."""

from app.db.base import Base
from app.models.ai import AiTask, ModelConfig
from app.models.catalog import Chapter, ChapterVersion, Novel, Volume
from app.models.memory import (
    ChapterSummary,
    EntityState,
    MemoryChangeProposal,
    StoryEntity,
    StoryEvent,
)
from app.models.quality import Foreshadowing, WritingGoal

__all__ = [
    "AiTask",
    "Base",
    "Chapter",
    "ChapterSummary",
    "ChapterVersion",
    "EntityState",
    "Foreshadowing",
    "MemoryChangeProposal",
    "ModelConfig",
    "Novel",
    "StoryEntity",
    "StoryEvent",
    "Volume",
    "WritingGoal",
]
