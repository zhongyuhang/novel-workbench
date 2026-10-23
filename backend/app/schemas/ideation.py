"""Requests and responses for guided design. Candidates are not formal rows."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

IdeationKind = Literal["guided", "world", "character"]
IdeationStatus = Literal["collecting", "generated"]
CandidateKind = Literal[
    "work_direction",
    "world_setting",
    "character_card",
    "character_relation",
    "character_arc",
]
CandidateStatus = Literal["pending", "accepted", "rejected", "deferred"]
ProviderMode = Literal["mock", "openai_compatible"]


def _blank_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class IdeationSessionCreate(BaseModel):
    kind: IdeationKind
    model_config_id: str | None = Field(default=None, max_length=36)
    use_mock: bool = False

    @field_validator("model_config_id")
    @classmethod
    def clean_model_id(cls, value: str | None) -> str | None:
        return _blank_id(value)


class IdeationAnswerCreate(BaseModel):
    question_id: str = Field(min_length=1, max_length=40)
    answer: str = Field(default="", max_length=4000)


class IdeationAccept(BaseModel):
    payload: dict[str, Any] | None = None


class IdeationChoice(BaseModel):
    id: str
    label: str


class IdeationQuestion(BaseModel):
    id: str
    prompt: str
    help_text: str
    optional: bool
    choices: list[IdeationChoice]


class IdeationAnswer(BaseModel):
    question_id: str
    prompt: str
    answer: str


class IdeationCandidateResponse(BaseModel):
    id: str
    session_id: str
    novel_id: str
    candidate_kind: CandidateKind
    title: str
    payload: dict[str, Any]
    status: CandidateStatus
    model_config_id: str | None
    model_name: str
    prompt_version: str
    applied: dict[str, Any] | None
    created_at: datetime
    reviewed_at: datetime | None


class IdeationSessionResponse(BaseModel):
    id: str
    novel_id: str
    kind: IdeationKind
    status: IdeationStatus
    step_index: int
    answers: list[IdeationAnswer]
    questions: list[IdeationQuestion]
    current_question: IdeationQuestion | None
    ready_to_generate: bool
    model_config_id: str | None
    provider_mode: ProviderMode
    model_name: str
    prompt_version: str
    simulated: bool
    candidates: list[IdeationCandidateResponse]
    created_at: datetime
    updated_at: datetime


class IdeationGenerateResponse(BaseModel):
    session: IdeationSessionResponse
    created_candidate_ids: list[str]
    manuscript_changed: bool
    formal_material_changed: bool
    provider_mode: ProviderMode
    model_config_id: str | None
    model_name: str
    simulated: bool
    note: str


class IdeationDecisionResponse(BaseModel):
    candidate: IdeationCandidateResponse
    manuscript_changed: bool
    formal_material_changed: bool
