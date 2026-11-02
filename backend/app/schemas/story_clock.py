"""Story-time anchor requests. Days are optional assists, not discourse order."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

AnchorKind = Literal["era", "event", "custom"]


class StoryTimeAnchorCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    kind: AnchorKind = "custom"
    base_day: int = Field(ge=-1_000_000, le=1_000_000)
    sort_order: int = Field(default=0, ge=0)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned == "":
            raise ValueError("名称不能为空")
        return cleaned


class StoryTimeAnchorUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=200)
    kind: AnchorKind | None = None
    base_day: int | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned == "":
            raise ValueError("名称不能为空")
        return cleaned


class StoryTimeAnchorResponse(BaseModel):
    id: str
    novel_id: str
    label: str
    kind: AnchorKind
    base_day: int
    sort_order: int
    created_at: datetime
    updated_at: datetime
