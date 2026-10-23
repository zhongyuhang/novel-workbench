"""Suspected-conflict hints.

This module only reads confirmed story events and the current chapter.
A change in entity state is not, by itself, a contradiction.
Nothing here updates chapters, entities, events, or proposals.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import enabled_default, endpoint_from_config, latest_enabled
from app.ai.prompts import CONFLICT_PROMPT_VERSION, build_conflict_prompt
from app.ai.provider import GenerationRequest, ModelEndpoint, ProviderError
from app.ai.registry import get_provider
from app.core.content import document_to_text
from app.core.errors import (
    InvalidReference,
    ModelConfigInvalid,
    NotFound,
    ProviderRequestFailed,
)
from app.models.ai import ModelConfig
from app.models.catalog import Chapter
from app.models.memory import StoryEvent
from app.repositories import catalog as catalog_repo
from app.schemas.quality import (
    ConflictCheckRequest,
    ConflictCheckResponse,
    ConflictType,
    Severity,
    SuspectedConflictResponse,
)

logger = logging.getLogger("app.quality.conflicts")

SUGGESTED_ACTION = (
    "请对照来源章节人工核对。确认是笔误、后来的情节变化，还是设定需要修订。"
    "这里只是疑似冲突，不会自动修改正文或正式记忆。"
)
_NO_AUTO_EDIT = "系统不会自动修改正文或正式记忆。"
_CLAIM = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9]{1,16})"
    r"(?:的([\u4e00-\u9fffA-Za-z0-9]{1,8}))?"
    r"是(?!不)"
    r"([\u4e00-\u9fffA-Za-z0-9]{1,16})"
)
_NEGATION = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9]{1,16})"
    r"(?:的([\u4e00-\u9fffA-Za-z0-9]{1,8}))?"
    r"(?:并不是|不是|并非)"
    r"([\u4e00-\u9fffA-Za-z0-9]{1,16})"
)
_SKIP_VALUES = {"一个", "这个", "那个", "什么", "这样", "那样"}
_CONFLICT_TYPES = {"attribute_contradiction", "negated_fact"}
_SEVERITIES = {"low", "medium", "high"}


@dataclass(frozen=True)
class ConfirmedFact:
    description: str
    source_chapter_id: str
    source_quote: str


@dataclass(frozen=True)
class _Claim:
    subject: str
    attribute: str
    value: str


@dataclass(frozen=True)
class SuspectedConflict:
    conflict_type: str
    manuscript_snippet: str
    confirmed_fact: str
    source_chapter_id: str
    source_quote: str
    severity: str
    confidence: float
    suggested_action: str


def find_suspected_conflicts(
    chapter_text: str,
    facts: list[ConfirmedFact],
) -> list[SuspectedConflict]:
    """Compare affirmative confirmed quotes with the current chapter. No writes."""

    prepared = [(fact, _positive_claims(fact.source_quote)) for fact in facts]
    found: list[SuspectedConflict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for sentence in _sentences(chapter_text):
        negations = _negation_claims(sentence)
        positives = _positive_claims(sentence)
        for fact, fact_claims in prepared:
            if not fact_claims:
                continue
            if sentence.strip() == fact.source_quote.strip():
                continue
            for claim in fact_claims:
                for negated in negations:
                    if _same_topic(negated, claim) and negated.value == claim.value:
                        _add(
                            found,
                            seen,
                            _hit(
                                "negated_fact",
                                sentence,
                                fact,
                                "high",
                                0.86,
                            ),
                        )
                for current in positives:
                    if _same_topic(current, claim) and current.value != claim.value:
                        _add(
                            found,
                            seen,
                            _hit(
                                "attribute_contradiction",
                                sentence,
                                fact,
                                "medium",
                                0.74,
                            ),
                        )
            if len(found) >= 20:
                return found
    return found


def parse_model_conflicts(
    raw: str,
    chapter_text: str,
    facts: list[ConfirmedFact],
) -> list[SuspectedConflict]:
    """Keep only hints whose snippet and quote are already in our materials."""

    data = _load_object(raw)
    items = data.get("conflicts")
    if not isinstance(items, list):
        raise ValueError("missing conflicts")
    by_quote = {fact.source_quote.strip(): fact for fact in facts if fact.source_quote.strip()}
    found: list[SuspectedConflict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        conflict_type = item.get("conflict_type")
        snippet = item.get("manuscript_snippet")
        quote = item.get("source_quote")
        severity = item.get("severity")
        if not isinstance(conflict_type, str) or conflict_type not in _CONFLICT_TYPES:
            continue
        snippet_text = snippet.strip() if isinstance(snippet, str) else ""
        if snippet_text == "" or snippet_text not in chapter_text:
            continue
        if not isinstance(quote, str):
            continue
        fact = by_quote.get(quote.strip())
        if fact is None:
            continue
        if not isinstance(severity, str) or severity not in _SEVERITIES:
            continue
        confidence = _confidence(item.get("confidence"))
        if confidence is None:
            continue
        action = item.get("suggested_action")
        text = action.strip() if isinstance(action, str) else ""
        if _NO_AUTO_EDIT not in text:
            text = f"{text} {_NO_AUTO_EDIT}".strip()
        _add(
            found,
            seen,
            SuspectedConflict(
                conflict_type=conflict_type,
                manuscript_snippet=snippet_text[:500],
                confirmed_fact=fact.description,
                source_chapter_id=fact.source_chapter_id,
                source_quote=fact.source_quote,
                severity=severity,
                confidence=confidence,
                suggested_action=text[:500],
            ),
        )
        if len(found) >= 20:
            break
    return found


def check_chapter_conflicts(
    session: Session,
    chapter_id: str,
    payload: ConflictCheckRequest,
) -> ConflictCheckResponse:
    chapter = catalog_repo.get_chapter(session, chapter_id)
    if chapter is None:
        raise NotFound("章节不存在。")
    text = document_to_text(chapter.content if isinstance(chapter.content, dict) else {})
    facts = _confirmed_facts(session, chapter.novel_id)
    mode, config, model_name = _resolve_mode(session, payload)
    if mode == "mock":
        conflicts = find_suspected_conflicts(text, facts)
        message = "已用本地规则检查疑似冲突。正文和正式记忆都没有改动。"
    else:
        if config is None:
            raise ModelConfigInvalid("找不到要使用的模型。")
        conflicts = _conflicts_from_model(config, text, facts)
        message = "已根据模型输出整理疑似冲突。正文和正式记忆都没有改动。"
    _refuse_staged_writes(session)
    titles = _chapter_titles(session, [item.source_chapter_id for item in conflicts])
    logger.info(
        "conflict check finished",
        extra={"count": len(conflicts), "mode": mode, "model_name": model_name},
    )
    return ConflictCheckResponse(
        chapter_id=chapter.id,
        novel_id=chapter.novel_id,
        provider_mode="mock" if mode == "mock" else "openai_compatible",
        prompt_version=CONFLICT_PROMPT_VERSION,
        manuscript_changed=False,
        formal_memory_changed=False,
        conflicts=[_response_item(item, titles) for item in conflicts],
        message=message,
        model_config_id=config.id if config is not None else None,
        model_name=model_name,
    )


def generate_conflict_text(*, endpoint: ModelEndpoint, prompt: str) -> str:
    provider = get_provider(endpoint)
    provider.validate_config(endpoint)
    result = provider.generate(
        GenerationRequest(
            endpoint=endpoint,
            prompt=prompt,
            max_output_tokens=endpoint.max_output_tokens,
        )
    )
    return result.text


def _conflicts_from_model(
    config: ModelConfig,
    text: str,
    facts: list[ConfirmedFact],
) -> list[SuspectedConflict]:
    prompt = build_conflict_prompt(
        chapter_text=text,
        facts=[(fact.source_chapter_id, fact.description, fact.source_quote) for fact in facts],
    )
    try:
        raw = generate_conflict_text(endpoint=_endpoint(config), prompt=prompt)
        return parse_model_conflicts(raw, text, facts)
    except ProviderError as exc:
        raise _public_provider_error(exc) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderRequestFailed(
            "MODEL_BAD_RESPONSE",
            "模型没有返回可解析的冲突提示。正文和正式记忆都没有改动。",
            502,
        ) from exc


def _confirmed_facts(session: Session, novel_id: str) -> list[ConfirmedFact]:
    """Confirmed events only. Entity state rows are intentionally ignored."""

    rows = session.scalars(
        select(StoryEvent).where(
            StoryEvent.novel_id == novel_id,
            StoryEvent.deleted_at.is_(None),
            StoryEvent.certainty == "confirmed",
        )
    ).all()
    facts: list[ConfirmedFact] = []
    for row in rows:
        if row.chapter_id is None:
            continue
        quote = row.evidence_quote.strip()
        if quote == "":
            continue
        description = row.description.strip() or quote
        facts.append(
            ConfirmedFact(
                description=description,
                source_chapter_id=row.chapter_id,
                source_quote=quote,
            )
        )
    return facts


def _resolve_mode(
    session: Session,
    payload: ConflictCheckRequest,
) -> tuple[str, ModelConfig | None, str]:
    if payload.model_config_id:
        config = session.get(ModelConfig, payload.model_config_id)
        if config is None:
            raise NotFound("模型配置不存在。")
        if not config.is_enabled:
            raise ModelConfigInvalid("这个模型配置已停用。")
        if payload.use_mock and config.provider_type != "mock":
            raise ModelConfigInvalid("模拟检查不能绑定外部模型。")
        if payload.use_mock or config.provider_type == "mock":
            return "mock", config, "本地规则"
        return "openai_compatible", config, config.model_name
    if payload.use_mock:
        return "mock", None, "本地规则"
    default = enabled_default(session)
    if default is not None:
        if default.provider_type == "mock":
            return "mock", default, "本地规则"
        return "openai_compatible", default, default.model_name
    found = latest_enabled(session, "openai_compatible")
    if found is None:
        return "mock", None, "本地规则"
    return "openai_compatible", found, found.model_name


def _endpoint(config: ModelConfig) -> ModelEndpoint:
    return endpoint_from_config(config)


def _chapter_titles(session: Session, chapter_ids: list[str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for chapter_id in chapter_ids:
        if chapter_id in titles:
            continue
        chapter = session.get(Chapter, chapter_id)
        titles[chapter_id] = chapter.title if chapter is not None else ""
    return titles


def _response_item(item: SuspectedConflict, titles: dict[str, str]) -> SuspectedConflictResponse:
    return SuspectedConflictResponse(
        conflict_type=_conflict_type(item.conflict_type),
        manuscript_snippet=item.manuscript_snippet,
        confirmed_fact=item.confirmed_fact,
        source_chapter_id=item.source_chapter_id,
        source_chapter_title=titles.get(item.source_chapter_id, ""),
        source_quote=item.source_quote,
        severity=_severity(item.severity),
        confidence=item.confidence,
        suggested_action=item.suggested_action,
    )


def _refuse_staged_writes(session: Session) -> None:
    if session.new or session.dirty or session.deleted:
        session.rollback()
        raise InvalidReference("冲突检查不会写入正文或正式记忆。")


def _public_provider_error(exc: ProviderError) -> ProviderRequestFailed:
    status = {
        "MODEL_TIMEOUT": 504,
        "MODEL_UNAVAILABLE": 503,
        "MODEL_RATE_LIMIT": 429,
        "MODEL_AUTH": 502,
        "MODEL_BAD_REQUEST": 422,
        "MODEL_BAD_RESPONSE": 502,
        "MODEL_CONFIG_INVALID": 422,
    }.get(exc.code, 502)
    return ProviderRequestFailed(
        exc.code,
        "冲突检查没有完成。正文和正式记忆都没有改动。",
        status,
    )


def _hit(
    conflict_type: str,
    sentence: str,
    fact: ConfirmedFact,
    severity: str,
    confidence: float,
) -> SuspectedConflict:
    return SuspectedConflict(
        conflict_type=conflict_type,
        manuscript_snippet=sentence.strip()[:500],
        confirmed_fact=fact.description,
        source_chapter_id=fact.source_chapter_id,
        source_quote=fact.source_quote,
        severity=severity,
        confidence=confidence,
        suggested_action=SUGGESTED_ACTION,
    )


def _add(
    found: list[SuspectedConflict],
    seen: set[tuple[str, str, str, str]],
    item: SuspectedConflict,
) -> None:
    key = (item.conflict_type, item.manuscript_snippet, item.source_quote, item.source_chapter_id)
    if key in seen:
        return
    seen.add(key)
    found.append(item)


def _positive_claims(text: str) -> list[_Claim]:
    spans = [match.span() for match in _NEGATION.finditer(text)]
    claims: list[_Claim] = []
    for match in _CLAIM.finditer(text):
        if _overlaps(match.span(), spans):
            continue
        claim = _claim(match.group(1), match.group(2) or "", match.group(3))
        if claim is not None:
            claims.append(claim)
    return claims


def _negation_claims(text: str) -> list[_Claim]:
    claims: list[_Claim] = []
    for match in _NEGATION.finditer(text):
        claim = _claim(match.group(1), match.group(2) or "", match.group(3))
        if claim is not None:
            claims.append(claim)
    return claims


def _claim(subject: str, attribute: str, value: str) -> _Claim | None:
    cleaned_subject = subject.strip()
    cleaned_value = value.strip()
    if len(cleaned_subject) < 2 or cleaned_value == "" or cleaned_value in _SKIP_VALUES:
        return None
    return _Claim(cleaned_subject, attribute.strip(), cleaned_value)


def _same_topic(left: _Claim, right: _Claim) -> bool:
    if left.attribute != right.attribute:
        return False
    return (
        left.subject == right.subject
        or left.subject.endswith(right.subject)
        or right.subject.endswith(left.subject)
    )


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(not (end <= other_start or start >= other_end) for other_start, other_end in spans)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？\n])", text)
    return [part.strip() for part in parts if part.strip()]


def _load_object(raw: str) -> dict[str, object]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json object")
    loaded = json.loads(raw[start : end + 1])
    if not isinstance(loaded, dict):
        raise ValueError("json is not an object")
    return cast(dict[str, object], loaded)


def _confidence(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if number < 0 or number > 1:
        return None
    return round(number, 2)


def _conflict_type(value: str) -> ConflictType:
    if value in _CONFLICT_TYPES:
        return cast(ConflictType, value)
    return "attribute_contradiction"


def _severity(value: str) -> Severity:
    if value in _SEVERITIES:
        return cast(Literal["low", "medium", "high"], value)
    return "medium"
