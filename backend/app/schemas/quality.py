"""Foreshadowing, suspected conflicts, and writing stats."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.catalog import ChapterResponse

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
    event_time_text: str | None = Field(default=None, max_length=200)
    character_discovered_text: str | None = Field(default=None, max_length=200)
    reader_revealed_text: str | None = Field(default=None, max_length=200)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        return _clean_required(value)

    @field_validator(
        "evidence_quote",
        "payoff_chapter_id",
        "event_time_text",
        "character_discovered_text",
        "reader_revealed_text",
    )
    @classmethod
    def clean_optional(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class ForeshadowingPatch(BaseModel):
    introduced_chapter_id: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    status: ForeshadowingStatus | None = None
    payoff_chapter_id: str | None = None
    evidence_quote: str | None = Field(default=None, max_length=2000)
    event_time_text: str | None = Field(default=None, max_length=200)
    character_discovered_text: str | None = Field(default=None, max_length=200)
    reader_revealed_text: str | None = Field(default=None, max_length=200)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_required(value)

    @field_validator(
        "evidence_quote",
        "payoff_chapter_id",
        "introduced_chapter_id",
        "event_time_text",
        "character_discovered_text",
        "reader_revealed_text",
    )
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
    event_time_text: str | None
    character_discovered_text: str | None
    reader_revealed_text: str | None
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
    model_config_id: str | None = None
    model_name: str | None = None


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


IssueType = Literal[
    "fact_continuity",
    "time_continuity",
    "character_continuity",
    "foreshadowing",
    "outline_execution",
    "text_surface",
]
IssueStatus = Literal[
    "pending",
    "confirmed",
    "ignored",
    "fixed",
    "expired",
    "deferred",
    "intentional",
]
AuthorStatus = Literal["pending", "confirmed", "ignored", "deferred", "intentional"]
FindingClass = Literal["deterministic", "suspected", "creative_risk"]
EvidenceStatus = Literal["sufficient", "insufficient"]
QualityProviderMode = Literal["rule", "mock", "openai_compatible"]
RepairApplyMode = Literal["replace_selection", "append"]
RepairStatus = Literal["proposed", "accepted", "rejected", "conflict"]


class QualityEvidence(BaseModel):
    kind: str
    label: str
    quote: str | None
    source_chapter_id: str | None
    source_chapter_title: str
    source_revision: int | None
    ref_id: str | None


class QualityRef(BaseModel):
    kind: str
    ref_id: str
    label: str


class RepairCandidateResponse(BaseModel):
    id: str
    issue_id: str
    novel_id: str
    chapter_id: str
    target_revision: int
    apply_mode: RepairApplyMode
    applicable: bool
    original_snippet: str
    replacement_text: str
    rationale: str
    diff_preview: str
    provider_mode: QualityProviderMode
    prompt_version: str
    status: RepairStatus
    created_at: datetime
    updated_at: datetime


class QualityIssueResponse(BaseModel):
    id: str
    novel_id: str
    chapter_id: str
    chapter_title: str
    issue_type: IssueType
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    status: IssueStatus
    finding_class: FindingClass
    manuscript_snippet: str
    target_revision: int | None
    location_note: str | None
    evidence_status: EvidenceStatus
    evidence: list[QualityEvidence]
    related_refs: list[QualityRef]
    rule_id: str
    rule_version: str
    analysis_version: str | None
    provider_mode: QualityProviderMode
    suggested_action: str
    fixed_revision: int | None
    recheck_count: int
    candidates: list[RepairCandidateResponse]
    created_at: datetime
    updated_at: datetime


class QualityCheckRequest(BaseModel):
    chapter_id: str | None = None
    use_model: bool = False
    model_config_id: str | None = None

    @field_validator("chapter_id", "model_config_id")
    @classmethod
    def clean_ids(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class QualityCheckResponse(BaseModel):
    novel_id: str
    chapter_id: str | None
    provider_mode: QualityProviderMode
    rule_version: str
    analysis_version: str | None
    manuscript_changed: Literal[False] = False
    formal_memory_changed: Literal[False] = False
    issue_count: int
    expired_count: int
    reopened_count: int
    issues: list[QualityIssueResponse]
    message: str
    model_config_id: str | None = None
    model_name: str | None = None


class QualityIssuePatch(BaseModel):
    status: AuthorStatus


class RepairGenerateRequest(BaseModel):
    use_model: bool = False
    model_config_id: str | None = None

    @field_validator("model_config_id")
    @classmethod
    def clean_model(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class RepairListResponse(BaseModel):
    issue_id: str
    manuscript_changed: Literal[False] = False
    formal_memory_changed: Literal[False] = False
    provider_mode: QualityProviderMode
    candidates: list[RepairCandidateResponse]
    message: str


class RepairAcceptRequest(BaseModel):
    target_revision: int = Field(ge=1)


class RepairDecisionResponse(BaseModel):
    manuscript_changed: bool
    formal_memory_changed: Literal[False] = False
    candidate: RepairCandidateResponse
    issue: QualityIssueResponse
    chapter: ChapterResponse | None
    message: str
