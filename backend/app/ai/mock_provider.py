"""Deterministic provider for tests and explicit mock runs. It never calls a network."""

import threading
from collections.abc import Iterator

from app.ai.provider import (
    GenerationRequest,
    GenerationResult,
    ModelEndpoint,
    ProviderError,
    StreamEvent,
    UsageEstimate,
)

_SCRIPTS: dict[str, "MockScript"] = {}
_SCRIPT_LOCK = threading.Lock()


class MockScript:
    """Block the generator before one token so tests can cancel or observe a heartbeat."""

    def __init__(self, hold_before: int) -> None:
        self.hold_before = hold_before
        self.reached = threading.Event()
        self.release = threading.Event()
        self.processed = threading.Event()

    def before_token(self, index: int) -> None:
        if index != self.hold_before:
            return
        self.reached.set()
        if not self.release.wait(timeout=8):
            raise ProviderError(
                "MODEL_TIMEOUT",
                "模拟生成等待过久，已停止。正文没有被修改。",
            )

    def after_token(self, index: int) -> None:
        if index == self.hold_before:
            self.processed.set()


def register_mock_script(script_id: str, script: MockScript) -> None:
    with _SCRIPT_LOCK:
        _SCRIPTS[script_id] = script


def pop_mock_script(script_id: str) -> None:
    with _SCRIPT_LOCK:
        _SCRIPTS.pop(script_id, None)


def lookup_mock_script(script_id: str) -> MockScript | None:
    with _SCRIPT_LOCK:
        return _SCRIPTS.get(script_id)


class MockProvider:
    def validate_config(self, endpoint: ModelEndpoint) -> None:
        if endpoint.model_name.strip() == "":
            raise ProviderError("MODEL_CONFIG_INVALID", "模拟模型需要一个模型名称。")

    def test_connection(self, endpoint: ModelEndpoint) -> None:
        self.validate_config(endpoint)
        behavior = _behavior(endpoint)
        if behavior == "timeout":
            raise ProviderError(
                "MODEL_TIMEOUT",
                "模型请求超时。请稍后重试，或调高超时时间。",
            )
        if behavior == "fail":
            raise ProviderError("MODEL_UNAVAILABLE", "模拟模型按配置返回失败。请检查参数。")

    def generate(self, request: GenerationRequest) -> GenerationResult:
        text = "".join(event.data for event in self.stream(request) if event.event == "token")
        return GenerationResult(text=text, usage=self.estimate_usage(request))

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]:
        self.validate_config(request.endpoint)
        behavior = _behavior(request.endpoint)
        if behavior == "timeout":
            raise ProviderError(
                "MODEL_TIMEOUT",
                "模型请求超时。生成没有写进正文。请稍后重试，或检查超时设置。",
            )
        if behavior == "timeout_after_tokens":
            tokens = _tokens(request.endpoint)
            for token in tokens:
                yield StreamEvent(event="token", data=token)
            raise ProviderError(
                "MODEL_TIMEOUT",
                "模型请求超时。请稍后重试，或检查超时设置。",
            )
        if behavior == "fail":
            raise ProviderError(
                "MODEL_UNAVAILABLE",
                "模型暂时不可用。生成没有写进正文。",
            )
        tokens = _tokens(request.endpoint)
        script = _script(request.endpoint)
        if script is None and _script_id(request.endpoint):
            raise ProviderError("MODEL_CONFIG_INVALID", "模拟脚本不存在，生成已停止。")
        for index, token in enumerate(tokens):
            if script is not None:
                script.before_token(index)
            yield StreamEvent(event="token", data=token)
            if script is not None:
                script.after_token(index)

    def estimate_usage(self, request: GenerationRequest) -> UsageEstimate:
        return UsageEstimate(
            input_tokens=max(1, len(request.prompt) // 4),
            output_tokens=None,
        )

    def normalize_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        return ProviderError("MODEL_UNAVAILABLE", "模型请求失败。请检查配置后重试。")


def _behavior(endpoint: ModelEndpoint) -> str:
    value = endpoint.parameters.get("mock_behavior")
    return value if isinstance(value, str) and value else "stream"


def _tokens(endpoint: ModelEndpoint) -> list[str]:
    raw = endpoint.parameters.get("mock_tokens")
    if isinstance(raw, list):
        tokens = [item for item in raw if isinstance(item, str) and item != ""]
        if tokens:
            return tokens
    return ["模拟", "候选"]


def _script_id(endpoint: ModelEndpoint) -> str:
    value = endpoint.parameters.get("mock_script_id")
    return value if isinstance(value, str) else ""


def _script(endpoint: ModelEndpoint) -> MockScript | None:
    script_id = _script_id(endpoint)
    if script_id == "":
        return None
    return lookup_mock_script(script_id)
