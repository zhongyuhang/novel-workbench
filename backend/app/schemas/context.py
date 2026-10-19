"""Structured context compiler payloads.

``token_estimate`` counts characters. It is an estimate, not a tokenizer count.
"""

from pydantic import BaseModel, Field, field_validator

from app.schemas.ai import TaskConstraints, TaskType, clean_material_ids


class ContextItem(BaseModel):
    id: str
    kind: str
    content: str
    source_type: str
    source_id: str | None = None
    source_revision: int | None = None
    certainty: str
    priority: int
    token_estimate: int
    included: bool
    exclusion_reason: str | None = None
    hit_reason: str
    warnings: list[str] = Field(default_factory=list)


class CompiledContext(BaseModel):
    task_type: str
    novel_id: str
    chapter_id: str | None
    target_revision: int | None
    items: list[ContextItem]
    total_token_estimate: int
    budget: int
    warnings: list[str]
    compiler_version: str
    context_hash: str
    legacy: bool = False


class ContextCompileRequest(BaseModel):
    novel_id: str = Field(min_length=1)
    chapter_id: str | None = None
    task_type: TaskType
    instruction: str = Field(default="", max_length=8000)
    selection_text: str | None = Field(default=None, max_length=20000)
    target_revision: int | None = Field(default=None, ge=1)
    constraints: TaskConstraints | None = None
    context_budget: int | None = Field(default=None, ge=200, le=20000)
    pinned_include: list[str] = Field(default_factory=list, max_length=40)
    pinned_exclude: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("instruction", "selection_text")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("pinned_include", "pinned_exclude")
    @classmethod
    def clean_pins(cls, value: list[str]) -> list[str]:
        return clean_material_ids(value)
