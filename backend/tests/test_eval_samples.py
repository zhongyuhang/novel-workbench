"""Fixed eval samples run through the mock provider and do not use the network."""

import json
from pathlib import Path

import httpx
import pytest

from app.ai.mock_provider import MockProvider
from app.ai.prompts import build_analyze_prompt, build_prompt
from app.ai.provider import GenerationRequest, ModelEndpoint

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "eval" / "samples.json"
_KINDS = {"continue", "rewrite", "summarize"}


def test_eval_samples_cover_continue_rewrite_and_summarize(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("eval sample tried to open a network client")

    monkeypatch.setattr(httpx, "Client", explode)
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    samples = payload["samples"]
    assert isinstance(samples, list)
    assert {item["kind"] for item in samples} == _KINDS
    assert [item["id"] for item in samples] == ["continue-rain", "rewrite-door", "summarize-key"]

    provider = MockProvider()
    for sample in samples:
        prompt = _prompt(sample)
        assert sample["chapter_text"] in prompt
        if sample["kind"] == "rewrite":
            assert sample["selection_text"] in prompt
            assert "选区" in prompt
            assert "选区改写" in prompt
        if sample["kind"] == "summarize":
            assert "不要改写正文" in prompt
        endpoint = ModelEndpoint(
            base_url="",
            model_name="mock-eval",
            api_key="",
            timeout_seconds=5,
            supports_streaming=True,
            provider_type="mock",
            parameters={"mock_tokens": sample["mock_tokens"]},
        )
        result = provider.generate(GenerationRequest(endpoint=endpoint, prompt=prompt))
        assert result.text == "".join(sample["mock_tokens"])
        assert result.text.strip() != ""


def _prompt(sample: dict[str, object]) -> str:
    kind = sample["kind"]
    chapter_text = str(sample["chapter_text"])
    if kind == "summarize":
        return build_analyze_prompt(title="评测章", chapter_text=chapter_text)
    constraints = sample["constraints"] if isinstance(sample["constraints"], dict) else None
    return build_prompt(
        task_type="rewrite" if kind == "rewrite" else "continue",
        instruction=str(sample["instruction"]),
        chapter_text=chapter_text,
        selection_text=str(sample["selection_text"]),
        constraints=constraints,
    )
