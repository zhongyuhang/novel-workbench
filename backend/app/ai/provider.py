"""Provider port. Business code depends on this shape, not on a vendor SDK.

No adapter is registered in M0. Calling a model requires a later milestone.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.secrets import mask_api_key


class ProviderError(Exception):
    def __init__(self, code: str, safe_message: str) -> None:
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


@dataclass(frozen=True, repr=False)
class ModelEndpoint:
    base_url: str
    model_name: str
    api_key: str
    timeout_seconds: float
    supports_streaming: bool

    def __repr__(self) -> str:
        masked = mask_api_key(self.api_key)
        return (
            "ModelEndpoint("
            f"base_url={self.base_url!r}, model_name={self.model_name!r}, "
            f"api_key={masked!r}, timeout_seconds={self.timeout_seconds!r}, "
            f"supports_streaming={self.supports_streaming!r})"
        )


@dataclass(frozen=True)
class GenerationRequest:
    endpoint: ModelEndpoint
    prompt: str
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class UsageEstimate:
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class GenerationResult:
    text: str
    usage: UsageEstimate


@dataclass(frozen=True)
class StreamEvent:
    event: str
    data: str


@runtime_checkable
class ModelProvider(Protocol):
    def validate_config(self, endpoint: ModelEndpoint) -> None: ...

    def test_connection(self, endpoint: ModelEndpoint) -> None: ...

    def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]: ...

    def estimate_usage(self, request: GenerationRequest) -> UsageEstimate: ...

    def normalize_error(self, exc: Exception) -> ProviderError: ...
