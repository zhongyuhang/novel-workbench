"""Catalog request and response models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.content import CANONICAL_CONTENT_FORMAT

NovelStatus = Literal["draft", "active", "archived"]
ChapterStatus = Literal["outline", "draft", "revised", "final"]
SaveKind = Literal["manual", "autosave"]
ChangeSource = Literal["manual", "ai_accepted", "restore", "import"]
ExportFormat = Literal["markdown", "txt"]


def _required_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise ValueError("标题不能为空")
    return title


class NovelCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    genre: str | None = Field(default=None, max_length=100)
    synopsis: str | None = Field(default=None, max_length=20000)
    style_guide: str | None = Field(default=None, max_length=20000)
    core_conflict: str | None = Field(default=None, max_length=20000)
    status: NovelStatus = "draft"

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _required_title(value)


class NovelUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    genre: str | None = Field(default=None, max_length=100)
    synopsis: str | None = Field(default=None, max_length=20000)
    style_guide: str | None = Field(default=None, max_length=20000)
    core_conflict: str | None = Field(default=None, max_length=20000)
    status: NovelStatus | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_title(value)


class NovelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    genre: str | None
    synopsis: str | None
    style_guide: str | None
    core_conflict: str | None
    status: NovelStatus
    created_at: datetime
    updated_at: datetime


class VolumeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _required_title(value)


class VolumeUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _required_title(value)


class VolumeReorder(BaseModel):
    novel_id: str = Field(min_length=1)
    volume_ids: list[str] = Field(default_factory=list)


class VolumeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    title: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ShellCleanupResponse(BaseModel):
    deleted: int = Field(ge=0)


class ChapterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    volume_id: str | None = None
    status: ChapterStatus = "draft"

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return _required_title(value)


class ChapterWrite(BaseModel):
    revision: int = Field(ge=1)
    content: dict[str, object]
    title: str | None = Field(default=None, max_length=200)
    status: ChapterStatus | None = None
    content_format: str | None = None
    save_kind: SaveKind = "manual"
    change_note: str | None = Field(default=None, max_length=500)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _required_title(value)

    @field_validator("content_format")
    @classmethod
    def canonical_format(cls, value: str | None) -> str | None:
        if value is not None and value != CANONICAL_CONTENT_FORMAT:
            raise ValueError("仅接受 tiptap_json")
        return value


class ChapterMove(BaseModel):
    volume_id: str | None
    sort_order: int = Field(ge=0)


class ChapterSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    volume_id: str | None
    title: str
    sort_order: int
    word_count: int
    status: ChapterStatus
    revision: int
    updated_at: datetime


class ChapterResponse(ChapterSummary):
    content: dict[str, object]
    content_format: str
    content_format_version: int
    created_at: datetime


class ChapterRestore(BaseModel):
    revision: int = Field(ge=1)
    version_id: str = Field(min_length=1, max_length=36)


class ChapterVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chapter_id: str
    revision: int
    content_format: str
    content_format_version: int
    change_source: ChangeSource
    change_note: str | None
    word_count: int
    preview: str
    ai_task_id: str | None = None
    repair_candidate_id: str | None = None
    created_at: datetime


class ChapterVersionDetailResponse(ChapterVersionResponse):
    text: str
    memory_proposal_ids: list[str]


class VersionDiffSide(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None
    revision: int
    change_source: ChangeSource | None
    change_note: str | None
    created_at: datetime
    word_count: int
    label: str
    ai_task_id: str | None = None
    repair_candidate_id: str | None = None
    memory_proposal_ids: list[str]


class TextDiffHunkResponse(BaseModel):
    op: Literal["equal", "insert", "delete"]
    text: str


class ChapterVersionDiffResponse(BaseModel):
    left: VersionDiffSide
    right: VersionDiffSide
    hunks: list[TextDiffHunkResponse]


class NovelExportRequest(BaseModel):
    format: ExportFormat


class SessionRequest(BaseModel):
    password: str = ""


class SessionResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
