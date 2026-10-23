"""Story planning requests and responses.

Confirmed rows are the only ones that count as binding constraints. Draft,
stale, and archived plans stay visible to the author and are not facts.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PlanningStatus = Literal["draft", "confirmed", "stale", "archived"]
EditablePlanningStatus = Literal["draft", "stale", "archived"]
StoryArcType = Literal["main", "subplot", "character", "other"]
ThreadVisibility = Literal["surface", "hidden"]
OutlineProviderMode = Literal["mock", "openai_compatible"]


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_id_list(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        entity_id = item.strip()
        if entity_id == "":
            raise ValueError("人物引用不能为空")
        if len(entity_id) > 36:
            raise ValueError("人物引用过长")
        if entity_id in seen:
            raise ValueError("同一场景不能重复引用同一个人物")
        seen.add(entity_id)
        cleaned.append(entity_id)
    return cleaned


class StoryPlanWrite(BaseModel):
    logline: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=20000)
    ending_intent: str | None = Field(default=None, max_length=2000)
    status: EditablePlanningStatus | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator("logline", "body", "ending_intent")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class PlanningConfirm(BaseModel):
    expected_revision: int = Field(ge=1)


class StoryPlanResponse(BaseModel):
    id: str
    novel_id: str
    logline: str | None
    body: str | None
    ending_intent: str | None
    status: PlanningStatus
    revision: int
    counts_as_fact: bool
    created_at: datetime
    updated_at: datetime


class StoryPlanView(BaseModel):
    novel_id: str
    plan: StoryPlanResponse | None


class ChapterOutlineWrite(BaseModel):
    goal: str | None = Field(default=None, max_length=500)
    must_advance: str | None = Field(default=None, max_length=4000)
    required_events: str | None = Field(default=None, max_length=4000)
    allowed_reveals: str | None = Field(default=None, max_length=4000)
    forbidden_reveals: str | None = Field(default=None, max_length=4000)
    target_words: int | None = Field(default=None, ge=1, le=200_000)
    ending_hook: str | None = Field(default=None, max_length=1000)
    status: EditablePlanningStatus | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator(
        "goal",
        "must_advance",
        "required_events",
        "allowed_reveals",
        "forbidden_reveals",
        "ending_hook",
    )
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ChapterOutlineResponse(BaseModel):
    id: str
    novel_id: str
    chapter_id: str
    goal: str | None
    must_advance: str | None
    required_events: str | None
    allowed_reveals: str | None
    forbidden_reveals: str | None
    target_words: int | None
    ending_hook: str | None
    status: PlanningStatus
    revision: int
    counts_as_fact: bool
    created_at: datetime
    updated_at: datetime


class ChapterOutlineView(BaseModel):
    novel_id: str
    chapter_id: str
    outline: ChapterOutlineResponse | None


class SceneCardWrite(BaseModel):
    goal: str | None = Field(default=None, max_length=500)
    location_entity_id: str | None = Field(default=None, max_length=36)
    character_entity_ids: list[str] = Field(default_factory=list, max_length=20)
    conflict: str | None = Field(default=None, max_length=2000)
    turning_point: str | None = Field(default=None, max_length=2000)
    expected_outcome: str | None = Field(default=None, max_length=2000)
    must_convey: str | None = Field(default=None, max_length=2000)
    must_not_reveal: str | None = Field(default=None, max_length=2000)
    status: PlanningStatus = "draft"
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator(
        "goal",
        "conflict",
        "turning_point",
        "expected_outcome",
        "must_convey",
        "must_not_reveal",
    )
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("location_entity_id")
    @classmethod
    def clean_location(cls, value: str | None) -> str | None:
        return _clean_id(value)

    @field_validator("character_entity_ids")
    @classmethod
    def clean_characters(cls, value: list[str]) -> list[str]:
        return _clean_id_list(value)


class SceneCardPatch(BaseModel):
    goal: str | None = Field(default=None, max_length=500)
    location_entity_id: str | None = Field(default=None, max_length=36)
    character_entity_ids: list[str] | None = Field(default=None, max_length=20)
    conflict: str | None = Field(default=None, max_length=2000)
    turning_point: str | None = Field(default=None, max_length=2000)
    expected_outcome: str | None = Field(default=None, max_length=2000)
    must_convey: str | None = Field(default=None, max_length=2000)
    must_not_reveal: str | None = Field(default=None, max_length=2000)
    status: PlanningStatus | None = None
    expected_revision: int = Field(ge=1)

    @field_validator(
        "goal",
        "conflict",
        "turning_point",
        "expected_outcome",
        "must_convey",
        "must_not_reveal",
    )
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("location_entity_id")
    @classmethod
    def clean_location(cls, value: str | None) -> str | None:
        return _clean_id(value)

    @field_validator("character_entity_ids")
    @classmethod
    def clean_characters(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_id_list(value)


class SceneReorder(BaseModel):
    scene_ids: list[str] = Field(min_length=1, max_length=200)


class StoryArcCreate(BaseModel):
    arc_type: StoryArcType = "main"
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    status: EditablePlanningStatus | None = None
    thread_visibility: ThreadVisibility | None = None

    @field_validator("title", "summary")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("title")
    @classmethod
    def title_required(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("故事线需要一个标题")
        return value


class StoryArcPatch(BaseModel):
    arc_type: StoryArcType | None = None
    title: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    status: EditablePlanningStatus | None = None
    thread_visibility: ThreadVisibility | None = None
    expected_revision: int = Field(ge=1)

    @field_validator("title", "summary")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class StoryArcReorder(BaseModel):
    arc_ids: list[str] = Field(min_length=1, max_length=200)


class StoryArcResponse(BaseModel):
    id: str
    novel_id: str
    arc_type: StoryArcType
    title: str
    summary: str | None
    thread_visibility: ThreadVisibility | None
    sort_order: int
    status: PlanningStatus
    revision: int
    counts_as_fact: bool
    created_at: datetime
    updated_at: datetime


class VolumeOutlineWrite(BaseModel):
    goal: str | None = Field(default=None, max_length=500)
    key_events: str | None = Field(default=None, max_length=4000)
    start_state: str | None = Field(default=None, max_length=2000)
    end_state: str | None = Field(default=None, max_length=2000)
    status: EditablePlanningStatus | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator("goal", "key_events", "start_state", "end_state")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class VolumeOutlineResponse(BaseModel):
    id: str
    novel_id: str
    volume_id: str
    goal: str | None
    key_events: str | None
    start_state: str | None
    end_state: str | None
    status: PlanningStatus
    revision: int
    counts_as_fact: bool
    created_at: datetime
    updated_at: datetime


class VolumeOutlineView(BaseModel):
    novel_id: str
    volume_id: str
    outline: VolumeOutlineResponse | None


class OutlineCandidateScene(BaseModel):
    goal: str | None = Field(default=None, max_length=500)
    conflict: str | None = Field(default=None, max_length=2000)
    turning_point: str | None = Field(default=None, max_length=2000)
    expected_outcome: str | None = Field(default=None, max_length=2000)
    must_convey: str | None = Field(default=None, max_length=2000)
    must_not_reveal: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "goal",
        "conflict",
        "turning_point",
        "expected_outcome",
        "must_convey",
        "must_not_reveal",
    )
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class OutlineCandidateRequest(BaseModel):
    use_mock: bool = True
    model_config_id: str | None = Field(default=None, max_length=36)
    include_scenes: bool = True

    @field_validator("model_config_id")
    @classmethod
    def clean_model(cls, value: str | None) -> str | None:
        return _clean_id(value)


class OutlineCandidatePreview(BaseModel):
    novel_id: str
    chapter_id: str
    provider_mode: OutlineProviderMode
    simulated: bool
    confirmed: Literal[False] = False
    manuscript_changed: Literal[False] = False
    written: Literal[False] = False
    note: str
    model_config_id: str | None = None
    model_name: str | None = None
    goal: str | None
    must_advance: str | None
    required_events: str | None
    allowed_reveals: str | None
    forbidden_reveals: str | None
    target_words: int | None
    ending_hook: str | None
    scenes: list[OutlineCandidateScene]


class OutlineCandidateAccept(BaseModel):
    goal: str | None = Field(default=None, max_length=500)
    must_advance: str | None = Field(default=None, max_length=4000)
    required_events: str | None = Field(default=None, max_length=4000)
    allowed_reveals: str | None = Field(default=None, max_length=4000)
    forbidden_reveals: str | None = Field(default=None, max_length=4000)
    target_words: int | None = Field(default=None, ge=1, le=200_000)
    ending_hook: str | None = Field(default=None, max_length=1000)
    scenes: list[OutlineCandidateScene] = Field(default_factory=list, max_length=12)
    expected_revision: int | None = Field(default=None, ge=1)

    @field_validator(
        "goal",
        "must_advance",
        "required_events",
        "allowed_reveals",
        "forbidden_reveals",
        "ending_hook",
    )
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class EntityRef(BaseModel):
    id: str
    name: str | None
    entity_type: str | None
    available: bool


class SceneCardResponse(BaseModel):
    id: str
    novel_id: str
    chapter_id: str
    sort_order: int
    goal: str | None
    location_entity_id: str | None
    location: EntityRef | None
    character_entity_ids: list[str]
    characters: list[EntityRef]
    conflict: str | None
    turning_point: str | None
    expected_outcome: str | None
    must_convey: str | None
    must_not_reveal: str | None
    status: PlanningStatus
    revision: int
    counts_as_fact: bool
    created_at: datetime
    updated_at: datetime


class OutlineCandidateAcceptResult(BaseModel):
    outline: ChapterOutlineResponse
    scenes: list[SceneCardResponse]
    manuscript_changed: Literal[False] = False
