"""Foreshadowing, suspected conflicts, and writing stats."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ForeshadowingStatus = Literal["open", "planned", "resolved", "abandoned", "uncertain"]
ConflictType = Literal["attribute_contradiction", "negated_fact"]
Severity = Literal["low", "medium", "high"]
ProviderMode = Literal["openai_compatible", "mock"]


def _clean_required(value: str) -> str:
    cleaned = value.strip()
    if cleaned == "":
        raise ValueError("内容不能为空")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class ForeshadowingCreate(BaseModel):
    introduced_chapter_id: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=4000)
    status: ForeshadowingStatus = "open"
    payoff_chapter_id: str | None = None
    evidence_quote: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        return _clean_required(value)

    @field_validator("evidence_quote", "payoff_chapter_id")
    @classmethod
    def clean_optional(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class ForeshadowingPatch(BaseModel):
    introduced_chapter_id: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    status: ForeshadowingStatus | None = None
    payoff_chapter_id: str | None = None
    evidence_quote: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_required(value)

    @field_validator("evidence_quote", "payoff_chapter_id", "introduced_chapter_id")
    @classmethod
    def clean_optional(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class ForeshadowingResponse(BaseModel):
    id: str
    novel_id: str
    introduced_chapter_id: str
    description: str
    status: ForeshadowingStatus
    payoff_chapter_id: str | None
    evidence_quote: str | None
    created_at: datetime
    updated_at: datetime


class ConflictCheckRequest(BaseModel):
    use_mock: bool = True
    model_config_id: str | None = None


class SuspectedConflictResponse(BaseModel):
    conflict_type: ConflictType
    manuscript_snippet: str
    confirmed_fact: str
    source_chapter_id: str
    source_chapter_title: str
    source_quote: str
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    suggested_action: str


class ConflictCheckResponse(BaseModel):
    chapter_id: str
    novel_id: str
    provider_mode: ProviderMode
    prompt_version: str
    manuscript_changed: Literal[False] = False
    formal_memory_changed: Literal[False] = False
    conflicts: list[SuspectedConflictResponse]
    message: str


class ChapterStat(BaseModel):
    chapter_id: str
    title: str
    volume_id: str | None
    sort_order: int
    word_count: int


class NovelStatsResponse(BaseModel):
    novel_id: str
    total_word_count: int
    chapter_count: int
    target_words: int | None
    chapters: list[ChapterStat]


class WritingGoalWrite(BaseModel):
    target_words: int = Field(ge=1, le=5_000_000)
