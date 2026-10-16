"""Turn chapter text or a model JSON payload into memory proposals.

Nothing in this module writes formal entities, events, or summaries.
"""

import json
import re
from dataclasses import dataclass

PROPOSAL_TYPES = {
    "entity_create",
    "entity_update",
    "entity_state",
    "story_event",
    "chapter_summary",
}
CERTAINTIES = {"confirmed", "inferred", "uncertain"}
ENTITY_TYPES = {"character", "location", "organization", "item", "rule", "other"}

_SPEECH = re.compile(r"([\u4e00-\u9fff]{2,4})(?:说道|问道|答道|喊道|笑道|冷声道)")
_NAMED = re.compile(r"(?:名叫|叫做|名为|自称)([\u4e00-\u9fffA-Za-z0-9]{1,12})")
_SUSPECT = re.compile(r"疑似([\u4e00-\u9fff]{2,8})")
_PLACE = re.compile(r"(?:来到|走进|抵达|回到)([\u4e00-\u9fff]{2,8})")
_EVENT_MARKERS = ("离开", "遇见", "杀死", "受伤", "得到", "失去", "发现", "答应")
_STOPWORDS = {
    "然后",
    "于是",
    "忽然",
    "突然",
    "但是",
    "可是",
    "因为",
    "所以",
    "如果",
    "虽然",
    "已经",
    "自己",
    "他们",
    "她们",
    "我们",
    "你们",
    "一个",
    "这个",
    "那个",
    "什么",
    "没有",
    "不是",
    "只是",
    "还是",
    "就是",
    "这样",
    "那样",
    "知道",
    "觉得",
    "看到",
    "听见",
    "开始",
    "最后",
    "后来",
    "当时",
    "现在",
    "今天",
    "明天",
}


@dataclass(frozen=True)
class ProposalDraft:
    proposal_type: str
    certainty: str
    evidence_quote: str
    payload: dict[str, object]
    evidence_in_source: bool


def extract_from_chapter(chapter_text: str) -> list[ProposalDraft]:
    """Deterministic mock analyzer. Quotes are taken from the chapter, or left empty."""

    text = chapter_text.strip()
    if text == "":
        return []
    drafts: list[ProposalDraft] = []
    seen: set[tuple[str, str]] = set()
    for name in _SPEECH.findall(text) + _NAMED.findall(text):
        _add_entity(drafts, seen, text, name, "character", uncertain=False)
    for name in _SUSPECT.findall(text):
        _add_entity(drafts, seen, text, name, "character", uncertain=True)
    for name in _PLACE.findall(text):
        _add_entity(drafts, seen, text, name, "location", uncertain=False)
    for sentence in _sentences(text):
        if not any(marker in sentence for marker in _EVENT_MARKERS):
            continue
        if len(drafts) >= 12:
            break
        quote = sentence if sentence in text else ""
        drafts.append(
            ProposalDraft(
                proposal_type="story_event",
                certainty="confirmed" if quote else "uncertain",
                evidence_quote=quote,
                evidence_in_source=quote != "",
                payload={
                    "description": sentence[:500],
                    "participants": [],
                    "event_time_text": None,
                    "evidence_in_source": quote != "",
                },
            )
        )
        if sum(1 for item in drafts if item.proposal_type == "story_event") >= 4:
            break
    summary_quote = _summary_quote(text)
    facts = [item[:180] for item in _sentences(text)[:3]]
    in_source = summary_quote in text and summary_quote != ""
    summary = ProposalDraft(
        proposal_type="chapter_summary",
        certainty="confirmed" if in_source else "uncertain",
        evidence_quote=summary_quote,
        evidence_in_source=in_source,
        payload={
            "summary": text[:400],
            "key_facts": facts,
            "evidence_in_source": in_source,
        },
    )
    return [*drafts[:11], summary]


def parse_analysis_output(raw: str, chapter_text: str) -> list[ProposalDraft]:
    """Parse a model payload. Confirmed claims without a source quote are downgraded."""

    data = _load_object(raw)
    items = data.get("proposals")
    if not isinstance(items, list):
        raise ValueError("missing proposals")
    drafts: list[ProposalDraft] = []
    for item in items:
        draft = _coerce_item(item, chapter_text)
        if draft is not None:
            drafts.append(draft)
        if len(drafts) >= 20:
            break
    return drafts


def _add_entity(
    drafts: list[ProposalDraft],
    seen: set[tuple[str, str]],
    text: str,
    name: str,
    entity_type: str,
    *,
    uncertain: bool,
) -> None:
    cleaned = name.strip()
    if cleaned == "" or cleaned in _STOPWORDS or (entity_type, cleaned) in seen:
        return
    if len(drafts) >= 12:
        return
    seen.add((entity_type, cleaned))
    if uncertain:
        drafts.append(
            ProposalDraft(
                proposal_type="entity_create",
                certainty="uncertain",
                evidence_quote="",
                evidence_in_source=False,
                payload={
                    "entity_type": entity_type,
                    "name": cleaned,
                    "aliases": [],
                    "profile": {"summary": "正文只作了不确定的暗示，没有可引用的证据。"},
                    "status": "unknown",
                    "evidence_in_source": False,
                },
            )
        )
        return
    quote = evidence_window(text, cleaned)
    in_source = quote != "" and quote in text
    drafts.append(
        ProposalDraft(
            proposal_type="entity_create",
            certainty="confirmed" if in_source else "uncertain",
            evidence_quote=quote,
            evidence_in_source=in_source,
            payload={
                "entity_type": entity_type,
                "name": cleaned,
                "aliases": [],
                "profile": {},
                "status": "active" if in_source else "unknown",
                "evidence_in_source": in_source,
            },
        )
    )


def evidence_window(text: str, needle: str, radius: int = 40) -> str:
    index = text.find(needle)
    if index < 0:
        return ""
    start = max(0, index - radius)
    end = min(len(text), index + len(needle) + radius)
    return text[start:end]


def _summary_quote(text: str) -> str:
    sentences = _sentences(text)
    if sentences:
        quote = sentences[0][:180]
        if quote in text:
            return quote
    quote = text[:180]
    return quote if quote in text else ""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?])", text)
    return [part.strip() for part in parts if part.strip()]


def _load_object(raw: str) -> dict[str, object]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("not json")
    loaded = json.loads(cleaned[start : end + 1])
    if not isinstance(loaded, dict):
        raise ValueError("not object")
    return {str(key): value for key, value in loaded.items()}


def _coerce_item(item: object, chapter_text: str) -> ProposalDraft | None:
    if not isinstance(item, dict):
        return None
    proposal_type = item.get("proposal_type")
    if proposal_type not in PROPOSAL_TYPES:
        return None
    certainty = item.get("certainty")
    if certainty not in CERTAINTIES:
        certainty = "uncertain"
    evidence = item.get("evidence_quote")
    quote = evidence.strip() if isinstance(evidence, str) else ""
    if len(quote) > 500:
        quote = quote[:500]
    in_source = quote != "" and quote in chapter_text
    if not in_source and certainty == "confirmed":
        certainty = "uncertain"
    if quote == "" and certainty == "confirmed":
        certainty = "uncertain"
    payload = item.get("payload")
    body = dict(payload) if isinstance(payload, dict) else {}
    normalized = _normalize_payload(str(proposal_type), body)
    if normalized is None:
        return None
    normalized["evidence_in_source"] = in_source
    return ProposalDraft(
        proposal_type=str(proposal_type),
        certainty=str(certainty),
        evidence_quote=quote if in_source else quote,
        evidence_in_source=in_source,
        payload=normalized,
    )


def _normalize_payload(proposal_type: str, body: dict[object, object]) -> dict[str, object] | None:
    if proposal_type == "entity_create":
        name = _text(body.get("name"))
        entity_type = body.get("entity_type")
        if name is None or entity_type not in ENTITY_TYPES:
            return None
        return {
            "entity_type": entity_type,
            "name": name,
            "aliases": _texts(body.get("aliases")),
            "profile": _object(body.get("profile")),
            "status": (
                body.get("status")
                if body.get("status") in {"active", "inactive", "unknown"}
                else "active"
            ),
        }
    if proposal_type in {"entity_update", "entity_state"}:
        target = _text(body.get("target_entity_id"))
        if target is None:
            return None
        payload: dict[str, object] = {"target_entity_id": target}
        if proposal_type == "entity_state":
            payload["state_data"] = _object(body.get("state_data"))
            return payload
        for key in ("entity_type", "name", "status"):
            if key in body:
                payload[key] = body[key]
        if "aliases" in body:
            payload["aliases"] = _texts(body.get("aliases"))
        if "profile" in body:
            payload["profile"] = _object(body.get("profile"))
        return payload
    if proposal_type == "story_event":
        description = _text(body.get("description"))
        if description is None:
            return None
        return {
            "description": description[:2000],
            "participants": _texts(body.get("participants")),
            "event_time_text": _text(body.get("event_time_text")),
        }
    summary = _text(body.get("summary"))
    if summary is None:
        return None
    return {"summary": summary[:4000], "key_facts": _texts(body.get("key_facts"))}


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _text(item)
        if text is not None:
            result.append(text[:80])
    return result[:20]


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}
