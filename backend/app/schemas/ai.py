"""Model settings and AI task payloads."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.catalog import ChapterResponse

ProviderType = Literal["openai_compatible", "mock"]
TaskType = Literal["continue", "rewrite", "polish", "expand", "shrink", "proofread"]
TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
ApplyMode = Literal["append", "insert", "replace_selection"]
ProviderMode = Literal["openai_compatible", "mock"]
Resolution = Literal["accepted", "rejected"]


def _clean_name(value: str) -> str:
    cleaned = value.strip()
    if cleaned == "":
        raise ValueError("名称不能为空")
    return cleaned


class ModelConfigWrite(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    provider_type: ProviderType = "openai_compatible"
    base_url: str = Field(default="", max_length=500)
    model_name: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    timeout_seconds: float = Field(default=60, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    temperature: float | None = Field(default=0.8, ge=0, le=2)
    max_output_tokens: int | None = Field(default=1200, ge=1, le=32000)
    supports_streaming: bool = True
    supports_json_output: bool = False
    is_enabled: bool = True

    @field_validator("display_name", "model_name")
    @classmethod
    def clean_required(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("base_url")
    @classmethod
    def clean_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned == "":
            raise ValueError("API Key 不能是空白")
        return cleaned


class ModelConfigPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    provider_type: ProviderType | None = None
    base_url: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=32000)
    supports_streaming: bool | None = None
    supports_json_output: bool | None = None
    is_enabled: bool | None = None

    @field_validator("display_name", "model_name")
    @classmethod
    def clean_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_name(value)

    @field_validator("base_url")
    @classmethod
    def clean_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().rstrip("/")

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned == "":
            raise ValueError("API Key 不能是空白")
        return cleaned


class ModelConfigResponse(BaseModel):
    id: str
    display_name: str
    provider_type: ProviderType
    base_url: str
    model_name: str
    api_key_configured: bool
    api_key_hint: str | None
    parameters: dict[str, object]
    capabilities: dict[str, object]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class ModelTestRequest(BaseModel):
    config_id: str | None = None
    provider_type: ProviderType | None = None
    base_url: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)

    @field_validator("base_url")
    @classmethod
    def clean_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().rstrip("/")

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ModelTestResponse(BaseModel):
    ok: bool
    provider_mode: ProviderMode
    message: str


class TaskConstraints(BaseModel):
    max_words: int | None = Field(default=None, ge=1, le=20000)
    viewpoint: str | None = Field(default=None, max_length=100)
    tone: str | None = Field(default=None, max_length=100)
    must_include: str | None = Field(default=None, max_length=2000)
    must_avoid: str | None = Field(default=None, max_length=2000)


class AiTaskCreate(BaseModel):
    novel_id: str = Field(min_length=1)
    chapter_id: str | None = None
    task_type: TaskType
    instruction: str = Field(default="", max_length=8000)
    selection_text: str | None = Field(default=None, max_length=20000)
    target_revision: int | None = Field(default=None, ge=1)
    model_config_id: str | None = None
    constraints: TaskConstraints | None = None
    use_mock: bool = False
    mock_behavior: str | None = Field(default=None, max_length=32)
    mock_tokens: list[str] | None = None
    mock_script_id: str | None = Field(default=None, max_length=64)

    @field_validator("instruction", "selection_text")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("mock_tokens")
    @classmethod
    def clean_tokens(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        tokens = [item for item in value if item != ""]
        if len(tokens) > 200:
            raise ValueError("模拟片段过多")
        if any(len(item) > 4000 for item in tokens):
            raise ValueError("模拟片段过长")
        return tokens

    @model_validator(mode="after")
    def mock_controls_require_mock(self) -> "AiTaskCreate":
        mock_controls = (
            self.mock_behavior is not None
            or self.mock_tokens is not None
            or self.mock_script_id is not None
        )
        if mock_controls and not self.use_mock:
            raise ValueError("模拟参数只能用于模拟模型")
        return self


class AiTaskResponse(BaseModel):
    id: str
    novel_id: str
    chapter_id: str | None
    task_type: TaskType
    status: TaskStatus
    model_config_id: str | None
    provider_mode: ProviderMode
    model_name: str
    prompt_version: str
    output_text: str | None
    error_code: str | None
    error_message_safe: str | None
    input_tokens: int | None
    output_tokens: int | None
    resolution: Resolution | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class AiTaskAccept(BaseModel):
    target_revision: int = Field(ge=1)
    apply_mode: ApplyMode


class AiTaskAcceptResponse(BaseModel):
    task: AiTaskResponse
    chapter: ChapterResponse
