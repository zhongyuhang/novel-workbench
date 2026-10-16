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
        if not endpoint.base_url.startswith(("http://", "https://")):
            raise ProviderError(
                "MODEL_CONFIG_INVALID",
                "Base URL 需要以 http:// 或 https:// 开头。",
            )
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
        if isinstance(exc, httpx.HTTPStatusError):
            return _status_error(exc.response.status_code)
        if isinstance(exc, httpx.HTTPError):
            return ProviderError("MODEL_UNAVAILABLE", "暂时连不上模型服务。请检查地址后重试。")
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
                        headers=_headers(endpoint.api_key),
                    )
                    if response.status_code in _RETRYABLE:
                        last_error = _status_error(response.status_code)
                        if attempt == attempts - 1:
                            raise last_error
                        self._sleep(_backoff(attempt))
                        continue
                    if response.status_code >= 400:
                        raise _status_error(response.status_code)
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
                headers=_headers(endpoint.api_key),
            ) as response,
        ):
            if response.status_code in _RETRYABLE or response.status_code >= 400:
                response.read()
                raise _status_error(response.status_code)
            for line in response.iter_lines():
                text = _delta_text(line)
                if text is None or text == "":
                    continue
                yield StreamEvent(event="token", data=text)

    def _client(self, endpoint: ModelEndpoint) -> httpx.Client:
        timeout = httpx.Timeout(
            endpoint.timeout_seconds,
            connect=min(10.0, endpoint.timeout_seconds),
        )
        return httpx.Client(timeout=timeout, transport=self._transport)


def _chat_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


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


def _delta_text(line: str) -> str | None:
    stripped = line.strip()
    if stripped == "" or not stripped.startswith("data:"):
        return None
    data = stripped.removeprefix("data:").strip()
    if data == "[DONE]":
        return None
    try:
        parsed = json.loads(data)
    except ValueError as exc:
        raise ProviderError("MODEL_BAD_RESPONSE", "模型流返回了无法解析的片段。") from exc
    if not isinstance(parsed, dict):
        return None
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return None
    content = delta.get("content")
    if content is None:
        return None
    if not isinstance(content, str):
        return None
    return content


def _status_error(status_code: int) -> ProviderError:
    if status_code in {401, 403}:
        return ProviderError("MODEL_AUTH", "模型服务拒绝了密钥。请检查 API Key 和权限。")
    if status_code in {400, 404, 422}:
        return ProviderError(
            "MODEL_BAD_REQUEST",
            "模型服务不接受当前参数。请检查模型名、地址和输出长度。",
        )
    if status_code == 429:
        return ProviderError("MODEL_RATE_LIMIT", "模型服务限流了。请稍后再试。")
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
