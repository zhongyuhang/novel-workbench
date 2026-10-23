"""Chronicle view and event-planning requests."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.memory import Certainty, StoryEventResponse

CandidateStatus = Literal["pending", "accepted", "rejected", "deferred"]
ProviderMode = Literal["mock", "openai_compatible"]


class ChronicleEventWrite(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=1, max_length=8000)
    event_time_text: str | None = Field(default=None, max_length=200)
    participants: list[str] = Field(default_factory=list)
    participant_entity_ids: list[str] = Field(default_factory=list)
    chapter_id: str | None = Field(default=None, max_length=36)
    story_arc_id: str | None = Field(default=None, max_length=36)
    foreshadowing_id: str | None = Field(default=None, max_length=36)
    evidence_quote: str | None = Field(default=None, max_length=8000)
    certainty: Certainty = "confirmed"
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator(
        "title",
        "event_time_text",
        "chapter_id",
        "story_arc_id",
        "foreshadowing_id",
        "evidence_quote",
    )
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned == "":
            raise ValueError("请填写事件")
        return cleaned

    @field_validator("participants")
    @classmethod
    def clean_names(cls, value: list[str]) -> list[str]:
        return _names(value)

    @field_validator("participant_entity_ids")
    @classmethod
    def clean_ids(cls, value: list[str]) -> list[str]:
        return _ids(value)


class ChronicleEventPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=8000)
    event_time_text: str | None = Field(default=None, max_length=200)
    participants: list[str] | None = None
    participant_entity_ids: list[str] | None = None
    chapter_id: str | None = Field(default=None, max_length=36)
    story_arc_id: str | None = Field(default=None, max_length=36)
    foreshadowing_id: str | None = Field(default=None, max_length=36)
    evidence_quote: str | None = Field(default=None, max_length=8000)
    certainty: Certainty | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator(
        "title",
        "description",
        "event_time_text",
        "chapter_id",
        "story_arc_id",
        "foreshadowing_id",
        "evidence_quote",
    )
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("participants")
    @classmethod
    def clean_names(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _names(value)

    @field_validator("participant_entity_ids")
    @classmethod
    def clean_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _ids(value)


class ChronicleView(BaseModel):
    novel_id: str
    events: list[StoryEventResponse]


class ChroniclePlanRequest(BaseModel):
    hint: str | None = Field(default=None, max_length=2000)
    model_config_id: str | None = Field(default=None, max_length=36)
    use_mock: bool = True

    @field_validator("hint", "model_config_id")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ChronicleCandidateResponse(BaseModel):
    id: str
    novel_id: str
    status: CandidateStatus
    title: str | None
    description: str
    event_time_text: str | None
    sort_order: int | None
    participants: list[str]
    participant_entity_ids: list[str]
    chapter_id: str | None
    story_arc_id: str | None
    foreshadowing_id: str | None
    evidence_quote: str
    certainty: Certainty
    hint: str | None
    model_config_id: str | None
    provider_mode: ProviderMode
    model_name: str
    prompt_version: str
    applied: dict[str, object] | None
    created_at: datetime
    reviewed_at: datetime | None


class ChroniclePlanResponse(BaseModel):
    novel_id: str
    provider_mode: ProviderMode
    simulated: bool
    model_config_id: str | None
    model_name: str
    prompt_version: str
    candidates: list[ChronicleCandidateResponse]
    manuscript_changed: Literal[False] = False
    formal_material_changed: Literal[False] = False
    note: str


class ChronicleAccept(BaseModel):
    event: ChronicleEventWrite | None = None
    review_note: str | None = Field(default=None, max_length=2000)

    @field_validator("review_note")
    @classmethod
    def blank_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ChronicleDecisionResponse(BaseModel):
    candidate: ChronicleCandidateResponse
    event: StoryEventResponse | None
    manuscript_changed: Literal[False] = False
    formal_material_changed: bool


def _names(value: list[str]) -> list[str]:
    if len(value) > 40:
        raise ValueError("参与者太多")
    names: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("参与者格式不对")
        cleaned = item.strip()
        if cleaned == "":
            continue
        if len(cleaned) > 80:
            raise ValueError("参与者名字过长")
        if cleaned not in names:
            names.append(cleaned)
    return names


def _ids(value: list[str]) -> list[str]:
    if len(value) > 40:
        raise ValueError("关联人物太多")
    found: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("人物编号格式不对")
        cleaned = item.strip()
        if cleaned == "":
            continue
        if len(cleaned) > 36:
            raise ValueError("人物编号过长")
        if cleaned not in found:
            found.append(cleaned)
    return found
