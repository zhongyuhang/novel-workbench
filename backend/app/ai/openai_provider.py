"""OpenAI Chat Completions compatible adapter. Vendor fields stay inside this module."""

import json
import time
from collections.abc import Callable, Iterator

import httpx

from app.ai.provider import (
    GenerationRequest,
    GenerationResult,
    ModelEndpoint,
    ProviderError,
    StreamEvent,
    UsageEstimate,
)
from app.ai.ssrf import UnsafeModelUrl, assert_base_url_allowed

_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_CODES = frozenset({"MODEL_TIMEOUT", "MODEL_UNAVAILABLE", "MODEL_RATE_LIMIT"})


class OpenAICompatibleProvider:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._transport = transport
        self._sleep = sleeper or time.sleep

    def validate_config(self, endpoint: ModelEndpoint) -> None:
        try:
            assert_base_url_allowed(endpoint.base_url)
        except UnsafeModelUrl as exc:
            if exc.message.startswith("Base URL 需要以"):
                raise ProviderError("MODEL_CONFIG_INVALID", exc.message) from exc
            raise ProviderError("MODEL_BASE_URL", exc.message) from exc
        if endpoint.model_name.strip() == "":
            raise ProviderError("MODEL_CONFIG_INVALID", "请填写模型名称。")
        if endpoint.api_key.strip() == "":
            raise ProviderError("MODEL_CONFIG_INVALID", "请填写 API Key。")
        if endpoint.timeout_seconds <= 0:
            raise ProviderError("MODEL_CONFIG_INVALID", "超时时间必须大于 0。")

    def test_connection(self, endpoint: ModelEndpoint) -> None:
        self.validate_config(endpoint)
        request = GenerationRequest(endpoint=endpoint, prompt="ping", max_output_tokens=1)
        self.generate(request)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.validate_config(request.endpoint)
        payload = _payload(request, stream=False)
        response = self._send(request.endpoint, payload)
        text = _message_text(response)
        usage = _usage(response) or self.estimate_usage(request)
        return GenerationResult(text=text, usage=usage)

    def stream(self, request: GenerationRequest) -> Iterator[StreamEvent]:
        self.validate_config(request.endpoint)
        if not request.endpoint.supports_streaming:
            result = self.generate(request)
            if result.text:
                yield StreamEvent(event="token", data=result.text)
            return
        payload = _payload(request, stream=True)
        attempts = request.endpoint.max_retries + 1
        for attempt in range(attempts):
            produced = False
            try:
                for event in self._stream_once(request.endpoint, payload):
                    produced = True
                    yield event
                return
            except ProviderError as exc:
                if produced or attempt == attempts - 1 or exc.code not in _RETRYABLE_CODES:
                    raise
                self._sleep(_backoff(attempt))
            except httpx.HTTPError as exc:
                normalized = self.normalize_error(exc)
                if produced or attempt == attempts - 1 or normalized.code not in _RETRYABLE_CODES:
                    raise normalized from exc
                self._sleep(_backoff(attempt))

    def estimate_usage(self, request: GenerationRequest) -> UsageEstimate:
        return UsageEstimate(input_tokens=max(1, len(request.prompt) // 4), output_tokens=None)

    def normalize_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, ProviderError):
            return exc
        if isinstance(exc, httpx.TimeoutException):
            return ProviderError(
                "MODEL_TIMEOUT",
                "模型请求超时。请稍后重试，或检查服务地址与超时设置。",
            )
        if isinstance(exc, httpx.ConnectError):
            return ProviderError("MODEL_BASE_URL", "连不上这个 Base URL。请检查地址是否正确。")
        if isinstance(exc, httpx.HTTPStatusError):
            return _status_error(exc.response.status_code, _error_hint(exc.response))
        if isinstance(exc, httpx.HTTPError):
            return ProviderError("MODEL_UNAVAILABLE", "网络失败，暂时连不上模型服务。")
        return ProviderError("MODEL_BAD_RESPONSE", "模型服务返回了无法使用的结果。")

    def _send(self, endpoint: ModelEndpoint, payload: dict[str, object]) -> dict[str, object]:
        attempts = endpoint.max_retries + 1
        last_error: ProviderError | None = None
        for attempt in range(attempts):
            try:
                with self._client(endpoint) as client:
                    response = client.post(
                        _chat_url(endpoint.base_url),
                        json=payload,
                        headers=_headers(endpoint),
                    )
                    if 300 <= response.status_code < 400:
                        raise ProviderError(
                            "MODEL_BASE_URL",
                            "模型地址返回了重定向，已拒绝跟随。",
                        )
                    hint = _error_hint(response)
                    if response.status_code in _RETRYABLE:
                        last_error = _status_error(response.status_code, hint)
                        if attempt == attempts - 1:
                            raise last_error
                        self._sleep(_backoff(attempt))
                        continue
                    if response.status_code >= 400:
                        raise _status_error(response.status_code, hint)
                    return _json_object(response)
            except httpx.HTTPError as exc:
                last_error = self.normalize_error(exc)
                if attempt == attempts - 1 or last_error.code not in _RETRYABLE_CODES:
                    raise last_error from exc
                self._sleep(_backoff(attempt))
                continue
        raise last_error or ProviderError("MODEL_UNAVAILABLE", "暂时连不上模型服务。")

    def _stream_once(
        self,
        endpoint: ModelEndpoint,
        payload: dict[str, object],
    ) -> Iterator[StreamEvent]:
        with (
            self._client(endpoint) as client,
            client.stream(
                "POST",
                _chat_url(endpoint.base_url),
                json=payload,
                headers=_headers(endpoint),
            ) as response,
        ):
            if 300 <= response.status_code < 400:
                response.read()
                raise ProviderError("MODEL_BASE_URL", "模型地址返回了重定向，已拒绝跟随。")
            if response.status_code in _RETRYABLE or response.status_code >= 400:
                response.read()
                raise _status_error(response.status_code, _error_hint(response))
            for line in response.iter_lines():
                yield from _events_from_line(line)

    def _client(self, endpoint: ModelEndpoint) -> httpx.Client:
        timeout = httpx.Timeout(
            endpoint.timeout_seconds,
            connect=min(10.0, endpoint.timeout_seconds),
        )
        return httpx.Client(timeout=timeout, transport=self._transport, follow_redirects=False)


def _chat_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _headers(endpoint: ModelEndpoint) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    for name, value in endpoint.extra_headers.items():
        if name.lower() in {"authorization", "content-type", "host", "content-length"}:
            continue
        headers[name] = value
    headers["Authorization"] = f"Bearer {endpoint.api_key}"
    return headers


def _payload(request: GenerationRequest, *, stream: bool) -> dict[str, object]:
    endpoint = request.endpoint
    payload: dict[str, object] = {
        "model": endpoint.model_name,
        "messages": [{"role": "user", "content": request.prompt}],
        "stream": stream,
    }
    temperature = endpoint.temperature
    if temperature is not None:
        payload["temperature"] = temperature
    limit = request.max_output_tokens
    if limit is None:
        limit = endpoint.max_output_tokens
    if isinstance(limit, int) and limit > 0:
        field_name = endpoint.parameters.get("token_limit_field")
        key = field_name if field_name == "max_completion_tokens" else "max_tokens"
        payload[key] = limit
    return payload


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderError("MODEL_BAD_RESPONSE", "模型服务返回了无法解析的内容。") from exc
    if not isinstance(body, dict):
        raise ProviderError("MODEL_BAD_RESPONSE", "模型服务返回了无法解析的内容。")
    return {str(key): value for key, value in body.items()}


def _message_text(body: dict[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("MODEL_BAD_RESPONSE", "模型服务没有返回候选文本。")
    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderError("MODEL_BAD_RESPONSE", "模型服务没有返回候选文本。")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ProviderError("MODEL_BAD_RESPONSE", "模型服务没有返回候选文本。")
    content = message.get("content")
    if not isinstance(content, str) or content.strip() == "":
        raise ProviderError("MODEL_BAD_RESPONSE", "模型没有返回可用文本。")
    return content


def _usage(body: dict[str, object]) -> UsageEstimate | None:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    return UsageEstimate(
        input_tokens=prompt if isinstance(prompt, int) else None,
        output_tokens=completion if isinstance(completion, int) else None,
    )


def _events_from_line(line: str) -> list[StreamEvent]:
    stripped = line.strip()
    if stripped == "" or not stripped.startswith("data:"):
        return []
    data = stripped.removeprefix("data:").strip()
    if data == "[DONE]":
        return []
    try:
        parsed = json.loads(data)
    except ValueError as exc:
        raise ProviderError("MODEL_BAD_RESPONSE", "模型流返回了无法解析的片段。") from exc
    if not isinstance(parsed, dict):
        return []
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        return []
    first = choices[0]
    if not isinstance(first, dict):
        return []
    events: list[StreamEvent] = []
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str) and content != "":
            events.append(StreamEvent(event="token", data=content))
    reason = first.get("finish_reason")
    if isinstance(reason, str) and reason.strip() != "":
        events.append(StreamEvent(event="finish", data=reason.strip().lower()))
    return events


def _error_hint(response: httpx.Response) -> str:
    try:
        raw = response.text
    except httpx.HTTPError:
        return ""
    return raw[:1000].lower()


def _model_missing(hint: str) -> bool:
    markers = (
        "model_not_found",
        "model not found",
        "model does not exist",
        "does not exist",
        "unknown model",
        "invalid model",
        "no such model",
    )
    return any(marker in hint for marker in markers)


def _status_error(status_code: int, hint: str = "") -> ProviderError:
    if status_code in {401, 403}:
        return ProviderError("MODEL_AUTH", "模型服务拒绝了密钥。请检查 API Key 和权限。")
    if status_code == 429:
        return ProviderError("MODEL_RATE_LIMIT", "模型服务限流了。请稍后再试。")
    if status_code == 404 and _model_missing(hint):
        return ProviderError("MODEL_NOT_FOUND", "模型不存在，或当前密钥无权使用它。")
    if status_code == 404:
        return ProviderError("MODEL_BASE_URL", "Base URL 不正确，或服务路径不存在。")
    if status_code in {400, 422} and _model_missing(hint):
        return ProviderError("MODEL_NOT_FOUND", "模型不存在，或当前密钥无权使用它。")
    if status_code in {400, 422}:
        return ProviderError(
            "MODEL_BAD_REQUEST",
            "模型服务不接受当前参数。请检查模型名、地址和输出长度。",
        )
    if status_code == 504:
        return ProviderError("MODEL_TIMEOUT", "模型请求超时。请稍后重试。")
    if status_code >= 500:
        return ProviderError("MODEL_UNAVAILABLE", "模型服务暂时不可用。请稍后重试。")
    return ProviderError("MODEL_BAD_RESPONSE", "模型服务返回了无法使用的结果。")


def _backoff(attempt: int) -> float:
    delay = 0.2
    for _ in range(max(0, attempt)):
        delay *= 2
    return min(2.0, delay)
