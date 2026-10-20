"""Model settings and AI task payloads."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.catalog import ChapterResponse

_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")
_BLOCKED_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "host",
        "content-length",
        "content-type",
        "transfer-encoding",
        "connection",
    }
)
TestStatus = Literal["untested", "success", "failed", "stale"]

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


def _clean_provider(value: str) -> str:
    cleaned = value.strip().lower()
    if _PROVIDER_ID.fullmatch(cleaned) is None:
        raise ValueError("服务商标识无效")
    return cleaned


def _clean_headers(value: dict[str, str] | None) -> dict[str, str] | None:
    if value is None:
        return None
    if len(value) > 20:
        raise ValueError("自定义 Header 过多")
    cleaned: dict[str, str] = {}
    for key, raw in value.items():
        name = key.strip()
        if _HEADER_NAME.fullmatch(name) is None or name.lower() in _BLOCKED_HEADERS:
            raise ValueError("自定义 Header 名称无效")
        if not isinstance(raw, str):
            raise ValueError("自定义 Header 值无效")
        text = raw.strip()
        if text == "" or "\n" in text or "\r" in text or len(text) > 500:
            raise ValueError("自定义 Header 值无效")
        cleaned[name] = text
    return cleaned


def clean_material_ids(value: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in value:
        text = item.strip()
        if text == "" or len(text) > 80:
            raise ValueError("材料编号无效")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


class ModelConfigWrite(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    provider: str = Field(default="custom", max_length=64)
    provider_type: ProviderType = "openai_compatible"
    base_url: str = Field(default="", max_length=500)
    model_name: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    custom_headers: dict[str, str] | None = None
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

    @field_validator("provider")
    @classmethod
    def clean_provider(cls, value: str) -> str:
        return _clean_provider(value)

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

    @field_validator("custom_headers")
    @classmethod
    def clean_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _clean_headers(value)


class ModelConfigPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    provider: str | None = Field(default=None, max_length=64)
    provider_type: ProviderType | None = None
    base_url: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    custom_headers: dict[str, str] | None = None
    clear_custom_headers: bool = False
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

    @field_validator("provider")
    @classmethod
    def clean_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_provider(value)

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

    @field_validator("custom_headers")
    @classmethod
    def clean_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _clean_headers(value)

    @model_validator(mode="after")
    def clear_flags_are_explicit(self) -> "ModelConfigPatch":
        if self.clear_api_key and self.api_key is not None:
            raise ValueError("清除密钥时不要同时提交新密钥")
        if self.clear_custom_headers and self.custom_headers is not None:
            raise ValueError("清除 Header 时不要同时提交新 Header")
        return self


class ModelConfigResponse(BaseModel):
    id: str
    display_name: str
    provider: str
    provider_type: ProviderType
    base_url: str
    model_name: str
    api_key_configured: bool
    api_key_hint: str | None
    custom_headers_configured: bool
    custom_header_names: list[str]
    parameters: dict[str, object]
    capabilities: dict[str, object]
    is_enabled: bool
    is_default: bool
    last_test_status: TestStatus
    last_tested_at: datetime | None
    last_test_error_code: str | None
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
    model_name: str | None = None
    elapsed_ms: int | None = None
    error_code: str | None = None


class ProviderPresetResponse(BaseModel):
    id: str
    label: str
    api_type: str
    default_base_url: str
    hint: str


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
