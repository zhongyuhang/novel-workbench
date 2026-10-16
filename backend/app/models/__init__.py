"""ORM models registered for Alembic metadata."""

from app.db.base import Base
from app.models.ai import AiTask, ModelConfig
from app.models.catalog import Chapter, ChapterVersion, Novel, Volume

__all__ = [
    "AiTask",
    "Base",
    "Chapter",
    "ChapterVersion",
    "ModelConfig",
    "Novel",
    "Volume",
]
