"""Responses for a versioned novel package. Bytes of the archive are not echoed back."""

from pydantic import BaseModel, Field

from app.schemas.catalog import NovelResponse


class PortableCounts(BaseModel):
    novels: int = 0
    volumes: int = 0
    chapters: int = 0
    chapter_versions: int = 0
    story_plans: int = 0
    chapter_outlines: int = 0
    scene_cards: int = 0
    entities: int = 0
    entity_states: int = 0
    relations: int = 0
    events: int = 0
    summaries: int = 0
    proposals: int = 0
    foreshadowing: int = 0
    writing_goals: int = 0
    quality_issues: int = 0
    repair_candidates: int = 0
    ai_tasks: int = 0
    model_configs: int = 0


class PortablePreviewResponse(BaseModel):
    format: str
    format_version: int
    novel_title: str
    can_import: bool
    message: str
    created: PortableCounts
    skipped: PortableCounts
    conflicts: PortableCounts
    invalid: PortableCounts
    warnings: list[str] = Field(default_factory=list)
    invalid_reasons: list[str] = Field(default_factory=list)
    conflict_map: dict[str, str] = Field(default_factory=dict)


class PortableImportResponse(BaseModel):
    novel: NovelResponse
    preview: PortablePreviewResponse
