"""OpenAI-compatible adapter behavior without a network."""

import httpx

from app.ai.openai_provider import OpenAICompatibleProvider
from app.ai.provider import GenerationRequest, ModelEndpoint

SECRET = "plain-secret-key-zz99"


def _endpoint(**overrides: object) -> ModelEndpoint:
    values: dict[str, object] = {
        "base_url": "https://example.invalid/v1",
        "model_name": "demo-model",
        "api_key": SECRET,
        "timeout_seconds": 5,
        "supports_streaming": True,
        "max_retries": 1,
        "temperature": 0.2,
        "max_output_tokens": 16,
    }
    values.update(overrides)
    return ModelEndpoint(
        base_url=str(values["base_url"]),
        model_name=str(values["model_name"]),
        api_key=str(values["api_key"]),
        timeout_seconds=float(values["timeout_seconds"]),  # type: ignore[arg-type]
        supports_streaming=bool(values["supports_streaming"]),
        max_retries=int(values["max_retries"]),  # type: ignore[arg-type]
        temperature=0.2,
        max_output_tokens=16,
    )


def test_stream_orders_deltas_and_hides_the_key() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        body = (
            'data: {"choices":[{"delta":{"content":"甲"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"乙"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body)

    provider = OpenAICompatibleProvider(
        transport=httpx.MockTransport(handler),
        sleeper=lambda _seconds: None,
    )
    events = list(provider.stream(GenerationRequest(endpoint=_endpoint(), prompt="写一句")))

    assert [event.data for event in events] == ["甲", "乙"]
    assert calls["count"] == 1
    rendered = "".join(event.data for event in events)
    assert SECRET not in rendered


def test_auth_failure_is_not_retried_and_message_hides_the_key() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            401,
            json={"error": {"message": f"rejected {request.headers['authorization']}"}},
        )

    provider = OpenAICompatibleProvider(
        transport=httpx.MockTransport(handler),
        sleeper=lambda _seconds: None,
    )
    try:
        provider.generate(GenerationRequest(endpoint=_endpoint(max_retries=2), prompt="ping"))
    except Exception as exc:
        message = str(exc)
        code = getattr(exc, "code", "")
    else:
        raise AssertionError("expected a provider error")

    assert calls["count"] == 1
    assert code == "MODEL_AUTH"
    assert SECRET not in message
    assert "Bearer" not in message
    assert "密钥" in message


def test_unavailable_status_retries_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "候选"}}], "usage": {"prompt_tokens": 3}},
        )

    sleeps: list[float] = []
    provider = OpenAICompatibleProvider(
        transport=httpx.MockTransport(handler),
        sleeper=sleeps.append,
    )
    result = provider.generate(GenerationRequest(endpoint=_endpoint(max_retries=1), prompt="ping"))

    assert result.text == "候选"
    assert calls["count"] == 2
    assert sleeps
    assert SECRET not in result.text


def test_validate_config_rejects_a_missing_key() -> None:
    provider = OpenAICompatibleProvider()
    try:
        provider.validate_config(_endpoint(api_key=""))
    except Exception as exc:
        assert getattr(exc, "code", "") == "MODEL_CONFIG_INVALID"
        assert "API Key" in str(exc)
    else:
        raise AssertionError("expected invalid config")
