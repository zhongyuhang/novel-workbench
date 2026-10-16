"""Memory request and response models."""

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EntityType = Literal["character", "location", "organization", "item", "rule", "other"]
EntityStatus = Literal["active", "inactive", "unknown"]
ProposalType = Literal[
    "entity_create",
    "entity_update",
    "entity_state",
    "story_event",
    "chapter_summary",
]
ProposalStatus = Literal["pending", "accepted", "rejected", "reverted", "stale"]
Certainty = Literal["confirmed", "inferred", "uncertain"]
SummaryStatus = Literal["current", "stale", "rejected"]
ProviderMode = Literal["openai_compatible", "mock"]


def _clean_name(value: str) -> str:
    cleaned = value.strip()
    if cleaned == "":
        raise ValueError("名称不能为空")
    return cleaned


def _clean_aliases(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        alias = item.strip()
        if alias == "" or alias.casefold() in seen:
            continue
        if len(alias) > 40:
            raise ValueError("别名过长")
        seen.add(alias.casefold())
        cleaned.append(alias)
    if len(cleaned) > 20:
        raise ValueError("别名过多")
    return cleaned


class EntityCreate(BaseModel):
    entity_type: EntityType
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)
    status: EntityStatus = "active"

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value: list[str]) -> list[str]:
        return _clean_aliases(value)

    @field_validator("profile")
    @classmethod
    def clean_profile(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_object(value)


class EntityUpdate(BaseModel):
    entity_type: EntityType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    profile: dict[str, Any] | None = None
    status: EntityStatus | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_name(value)

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_aliases(value)

    @field_validator("profile")
    @classmethod
    def clean_profile(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return _bounded_object(value)


class EntityStateResponse(BaseModel):
    id: str
    entity_id: str
    chapter_id: str
    chapter_title: str
    source_revision: int | None
    state_data: dict[str, Any]
    evidence_quote: str | None
    source_type: Literal["manual", "ai_proposal", "import"]
    created_at: datetime


class EntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    entity_type: EntityType
    name: str
    aliases: list[str]
    profile: dict[str, Any]
    status: EntityStatus
    created_at: datetime
    updated_at: datetime
    states: list[EntityStateResponse]


class AnalyzeRequest(BaseModel):
    revision: int = Field(ge=1)
    model_config_id: str | None = None
    use_mock: bool = False


class ProposalResponse(BaseModel):
    id: str
    novel_id: str
    source_chapter_id: str
    source_chapter_title: str
    source_revision: int
    proposal_type: ProposalType
    payload: dict[str, Any]
    evidence_quote: str
    certainty: Certainty
    evidence_in_source: bool
    status: ProposalStatus
    review_note: str | None
    applied_entity_id: str | None
    applied_state_id: str | None
    applied_event_id: str | None
    applied_summary_id: str | None
    created_at: datetime
    reviewed_at: datetime | None


class AnalyzeResponse(BaseModel):
    chapter_id: str
    novel_id: str
    source_revision: int
    status: Literal["completed"]
    provider_mode: ProviderMode
    model_name: str
    prompt_version: str
    proposal_count: int
    proposals: list[ProposalResponse]
    message: str
    formal_memory_changed: Literal[False] = False
    manuscript_changed: Literal[False] = False


class ReviewRequest(BaseModel):
    review_note: str | None = Field(default=None, max_length=2000)

    @field_validator("review_note")
    @classmethod
    def clean_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ChapterSummaryResponse(BaseModel):
    id: str
    novel_id: str
    chapter_id: str
    chapter_title: str
    summary: str
    key_facts: list[str]
    source_revision: int
    chapter_revision: int
    model_name: str | None
    status: SummaryStatus
    created_at: datetime
    updated_at: datetime


class StoryEventResponse(BaseModel):
    id: str
    novel_id: str
    chapter_id: str
    chapter_title: str
    source_revision: int | None
    chapter_revision: int
    event_time_text: str | None
    description: str
    participants: list[str]
    evidence_quote: str
    certainty: Certainty
    created_at: datetime


def _bounded_object(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False)
    if len(encoded) > 20000:
        raise ValueError("档案过长")
    return value
