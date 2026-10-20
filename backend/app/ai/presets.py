"""Data-driven provider presets. Adding a row does not change request logic."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

_PRESET_PATH = Path(__file__).with_name("provider_presets.json")


class ProviderPreset(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    api_type: str = Field(min_length=1, max_length=64)
    default_base_url: str = ""
    hint: str = ""


@lru_cache
def load_provider_presets() -> tuple[ProviderPreset, ...]:
    raw = json.loads(_PRESET_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RuntimeError("provider presets must be a list")
    return tuple(ProviderPreset.model_validate(item) for item in raw)
