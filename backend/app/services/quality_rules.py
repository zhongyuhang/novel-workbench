"""Offline quality rules.

These functions only read the materials they are given. They never write a
chapter, a setting, or a database row. Every finding is a suspected issue.
Subjective claims such as "the character is unreasonable" are not emitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.services.conflicts import ConfirmedFact, find_suspected_conflicts

RULE_VERSION = "quality_rules_v1"
MODEL_VERSION = "quality_model_v1"
_NO_AUTO = "这是疑似问题，不会自动修改正文或正式记忆。"
_MAX_FINDINGS = 40
_LONG_OPEN_GAP = 3
_STATE_KEYS = {
    "location": "位置",
    "injury": "伤势",
    "possession": "持有物",
    "age": "年龄",
    "identity": "身份",
    "ability": "能力",
    "holder": "持有者",
    "position": "职位",
    "位置": "位置",
    "伤势": "伤势",
    "持有物": "持有物",
    "年龄": "年龄",
    "身份": "身份",
    "能力": "能力",
    "职位": "职位",
}
_ISSUE_TYPES = {
    "fact_continuity",
    "time_continuity",
    "character_continuity",
    "foreshadowing",
    "outline_execution",
    "text_surface",
}
_SEVERITIES = {"low", "medium", "high"}
_BANNED_CLAIMS = ("性格不合理", "剧情存在逻辑错误", "人物性格有问题")
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_CN_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_DAY = re.compile(r"第(\d+)天")
_CHAPTER_TIME = re.compile(r"第(\d+)章")
_TIME_HINT = re.compile(r"第|年|月|日|天")
_CALLED = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9]{1,16})(?:叫做|名叫|名为)([\u4e00-\u9fffA-Za-z0-9]{1,16})"
)
_PUNCT = re.compile(r"。{2,}|，{2,}|！{2,}|？{2,}")


@dataclass(frozen=True)
class Evidence:
    kind: str
    label: str
    quote: str | None
    source_chapter_id: str | None
    source_revision: int | None
    ref_id: str | None


@dataclass(frozen=True)
class RelatedRef:
    kind: str
    ref_id: str
    label: str


@dataclass(frozen=True)
class QualityFinding:
    issue_type: str
    rule_id: str
    severity: str
    confidence: float
    chapter_id: str
    manuscript_snippet: str
    target_revision: int | None
    location_note: str | None
    evidence_status: str
    evidence: tuple[Evidence, ...]
    related_refs: tuple[RelatedRef, ...]
    suggested_action: str
    fingerprint_key: str
    reading_index: int


@dataclass(frozen=True)
class ChapterMaterial:
    id: str
    title: str
    reading_index: int
    revision: int
    text: str


@dataclass(frozen=True)
class EventMaterial:
    id: str
    chapter_id: str
    description: str
    evidence_quote: str
    event_time_text: str | None
    participants: tuple[str, ...]
    source_revision: int | None


@dataclass(frozen=True)
class StateMaterial:
    id: str
    entity_id: str
    entity_name: str
    chapter_id: str
    values: tuple[tuple[str, str], ...]
    evidence_quote: str | None
    valid_from_text: str | None
    valid_until_text: str | None
    source_revision: int | None


@dataclass(frozen=True)
class RelationMaterial:
    id: str
    from_name: str
    to_name: str
    relation_type: str
    evidence_quote: str | None
    source_chapter_id: str | None
    source_revision: int | None


@dataclass(frozen=True)
class OutlineMaterial:
    id: str
    chapter_id: str
    required_events: str | None
    must_advance: str | None
    forbidden_reveals: str | None


@dataclass(frozen=True)
class SceneMaterial:
    id: str
    chapter_id: str
    must_convey: str | None
    must_not_reveal: str | None


@dataclass(frozen=True)
class ForeshadowMaterial:
    id: str
    description: str
    status: str
    introduced_chapter_id: str
    payoff_chapter_id: str | None
    evidence_quote: str | None


@dataclass(frozen=True)
class EntityMaterial:
    id: str
    name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class QualityMaterials:
    chapters: tuple[ChapterMaterial, ...]
    events: tuple[EventMaterial, ...]
    states: tuple[StateMaterial, ...]
    relations: tuple[RelationMaterial, ...]
    outlines: tuple[OutlineMaterial, ...]
    scenes: tuple[SceneMaterial, ...]
    foreshadowing: tuple[ForeshadowMaterial, ...]
    entities: tuple[EntityMaterial, ...]
    focus_chapter_id: str | None = None


@dataclass(frozen=True)
class _Point:
    scale: str
    value: int


def run_rules(materials: QualityMaterials) -> list[QualityFinding]:
    """Return a stable list of suspected findings. Same input, same output."""

    chapters = tuple(sorted(materials.chapters, key=lambda item: (item.reading_index, item.id)))
    by_id = {item.id: item for item in chapters}
    focus = materials.focus_chapter_id
    found: list[QualityFinding] = []
    _facts(found, materials.events, chapters, by_id, focus)
    _state_time(found, materials.states, by_id, focus)
    _event_order(found, materials.events, by_id, focus)
    _relations(found, materials.relations, chapters, focus)
    _foreshadowing(found, materials.foreshadowing, chapters, by_id, focus)
    _outlines(found, materials.outlines, by_id, focus)
    _scenes(found, materials.scenes, by_id, focus)
    _surface(found, chapters, materials.entities, focus)
    found.sort(
        key=lambda item: (item.reading_index, item.issue_type, item.rule_id, item.fingerprint_key)
    )
    return found[:_MAX_FINDINGS]


def materials_from_mapping(payload: dict[str, object]) -> QualityMaterials:
    """Build rule input from an offline eval case. Unknown keys are ignored."""

    return QualityMaterials(
        chapters=_chapters(payload.get("chapters")),
        events=_events(payload.get("events")),
        states=_states(payload.get("states")),
        relations=_relations_in(payload.get("relations")),
        outlines=_outlines_in(payload.get("outlines")),
        scenes=_scenes_in(payload.get("scenes")),
        foreshadowing=_foreshadow_in(payload.get("foreshadowing")),
        entities=_entities(payload.get("entities")),
        focus_chapter_id=_optional_str(payload.get("focus_chapter_id")),
    )


def model_findings_from_payload(
    raw_items: object,
    *,
    chapter: ChapterMaterial,
    known_quotes: dict[str, Evidence],
) -> list[QualityFinding]:
    """Keep model hints whose snippet is actually in the chapter text."""

    if not isinstance(raw_items, list):
        return []
    found: list[QualityFinding] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        parsed = _model_item(item, chapter, known_quotes)
        if parsed is not None:
            found.append(parsed)
        if len(found) >= 8:
            break
    return found


def _facts(
    found: list[QualityFinding],
    events: tuple[EventMaterial, ...],
    chapters: tuple[ChapterMaterial, ...],
    by_id: dict[str, ChapterMaterial],
    focus: str | None,
) -> None:
    facts: list[ConfirmedFact] = []
    owners: dict[str, EventMaterial] = {}
    for event in events:
        quote = event.evidence_quote.strip()
        if quote == "":
            continue
        facts.append(
            ConfirmedFact(
                description=event.description.strip() or quote,
                source_chapter_id=event.chapter_id,
                source_quote=quote,
            )
        )
        owners.setdefault(quote, event)
    for chapter in _scoped(chapters, focus):
        for hit in find_suspected_conflicts(chapter.text, facts):
            owner = owners.get(hit.source_quote.strip())
            if owner is None:
                continue
            source = by_id.get(owner.chapter_id)
            evidence = (
                Evidence(
                    "manuscript",
                    "当前正文片段",
                    hit.manuscript_snippet,
                    chapter.id,
                    chapter.revision,
                    None,
                ),
                Evidence(
                    "story_event",
                    owner.description or "已确认事实",
                    owner.evidence_quote,
                    owner.chapter_id,
                    owner.source_revision,
                    owner.id,
                ),
            )
            _add(
                found,
                issue_type="fact_continuity",
                rule_id=f"fact.{hit.conflict_type}",
                severity=hit.severity,
                confidence=hit.confidence,
                chapter=chapter,
                snippet=hit.manuscript_snippet,
                location_note=None,
                evidence_status="sufficient",
                evidence=evidence,
                refs=(
                    RelatedRef(
                        "story_event",
                        owner.id,
                        owner.description or owner.evidence_quote,
                    ),
                ),
                action=(
                    f"正文和已确认事实的说法不一致。来源是"
                    f"《{source.title if source else '未知章节'}》。请作者核对后再决定改哪里。"
                ),
                key="|".join(
                    (
                        f"fact.{hit.conflict_type}",
                        chapter.id,
                        owner.id,
                        hit.manuscript_snippet,
                        hit.source_quote,
                    )
                ),
                insufficient=False,
            )


def _state_time(
    found: list[QualityFinding],
    states: tuple[StateMaterial, ...],
    by_id: dict[str, ChapterMaterial],
    focus: str | None,
) -> None:
    grouped: dict[tuple[str, str], list[tuple[StateMaterial, str]]] = {}
    for state in states:
        for key, value in state.values:
            label = _STATE_KEYS.get(key)
            if label is None or value.strip() == "":
                continue
            grouped.setdefault((state.entity_id, key), []).append((state, value.strip()))
    for (_entity_id, key), rows in grouped.items():
        label = _STATE_KEYS[key]
        for index, (left, left_value) in enumerate(rows):
            for right, right_value in rows[index + 1 :]:
                if left_value == right_value:
                    continue
                if focus is not None and focus not in {left.chapter_id, right.chapter_id}:
                    continue
                kind = _interval_kind(
                    left.valid_from_text,
                    left.valid_until_text,
                    right.valid_from_text,
                    right.valid_until_text,
                )
                if kind in {"incomplete", "separate"}:
                    continue
                later = _later_state(left, right, by_id)
                chapter = by_id.get(later.chapter_id)
                if chapter is None:
                    continue
                insufficient = kind == "undetermined"
                _add(
                    found,
                    issue_type="time_continuity",
                    rule_id="time.validity_overlap"
                    if not insufficient
                    else "time.validity_undetermined",
                    severity="low" if insufficient else "high",
                    confidence=0.4 if insufficient else 0.8,
                    chapter=chapter,
                    snippet=later.evidence_quote or "",
                    location_note=(
                        f"{later.entity_name}的{label}在两段有效时间上分别是"
                        f"「{left_value}」和「{right_value}」。"
                    ),
                    evidence_status="insufficient" if insufficient else "sufficient",
                    evidence=(
                        _state_evidence(left, label, left_value),
                        _state_evidence(right, label, right_value),
                    ),
                    refs=(
                        RelatedRef("entity_state", left.id, f"{left.entity_name}的{label}"),
                        RelatedRef("entity_state", right.id, f"{right.entity_name}的{label}"),
                    ),
                    action=(
                        "两段状态的有效时间无法比较。"
                        if insufficient
                        else "两段已记录状态的有效时间疑似重叠，但取值不同。状态变化本身不是矛盾。"
                    ),
                    key="|".join(
                        sorted((left.id, right.id))
                        + [key, "undetermined" if insufficient else "overlap"]
                    ),
                    insufficient=insufficient,
                )


def _event_order(
    found: list[QualityFinding],
    events: tuple[EventMaterial, ...],
    by_id: dict[str, ChapterMaterial],
    focus: str | None,
) -> None:
    usable = [event for event in events if (event.event_time_text or "").strip()]
    for index, left in enumerate(usable):
        left_chapter = by_id.get(left.chapter_id)
        if left_chapter is None:
            continue
        for right in usable[index + 1 :]:
            right_chapter = by_id.get(right.chapter_id)
            if right_chapter is None or left_chapter.id == right_chapter.id:
                continue
            if not _share(left.participants, right.participants):
                continue
            if focus is not None and focus not in {left.chapter_id, right.chapter_id}:
                continue
            earlier, later, early_event, late_event = _by_reading(
                left_chapter,
                right_chapter,
                left,
                right,
            )
            kind = _order_kind(early_event.event_time_text, late_event.event_time_text)
            if kind == "ok":
                continue
            insufficient = kind == "undetermined"
            _add(
                found,
                issue_type="time_continuity",
                rule_id="time.event_order" if not insufficient else "time.event_order_undetermined",
                severity="low" if insufficient else "medium",
                confidence=0.35 if insufficient else 0.72,
                chapter=later,
                snippet=late_event.evidence_quote or late_event.description,
                location_note=(
                    f"较早章节《{earlier.title}》的故事时间是"
                    f"「{early_event.event_time_text or ''}」，较晚章节《{later.title}》是"
                    f"「{late_event.event_time_text or ''}」。"
                ),
                evidence_status="insufficient" if insufficient else "sufficient",
                evidence=(
                    Evidence(
                        "story_event",
                        early_event.description,
                        early_event.evidence_quote or early_event.description,
                        earlier.id,
                        early_event.source_revision,
                        early_event.id,
                    ),
                    Evidence(
                        "story_event",
                        late_event.description,
                        late_event.evidence_quote or late_event.description,
                        later.id,
                        late_event.source_revision,
                        late_event.id,
                    ),
                ),
                refs=(
                    RelatedRef("story_event", early_event.id, early_event.description),
                    RelatedRef("story_event", late_event.id, late_event.description),
                ),
                action=(
                    "两个事件都写了故事时间，但格式对不上，无法判断先后。"
                    if insufficient
                    else "章节顺序和故事时间疑似相反。请作者核对日历或章节顺序。"
                ),
                key="|".join(sorted((early_event.id, late_event.id)) + [kind]),
                insufficient=insufficient,
            )


def _relations(
    found: list[QualityFinding],
    relations: tuple[RelationMaterial, ...],
    chapters: tuple[ChapterMaterial, ...],
    focus: str | None,
) -> None:
    for relation in relations:
        kind = relation.relation_type.strip()
        if kind == "" or relation.from_name.strip() == "" or relation.to_name.strip() == "":
            continue
        needles = (
            f"{relation.from_name}不是{relation.to_name}的{kind}",
            f"{relation.from_name}与{relation.to_name}并非{kind}",
            f"{relation.from_name}和{relation.to_name}不是{kind}",
        )
        for chapter in _scoped(chapters, focus):
            hit = next((needle for needle in needles if needle in chapter.text), None)
            if hit is None:
                continue
            sentence = _sentence_with(chapter.text, hit)
            _add(
                found,
                issue_type="character_continuity",
                rule_id="character.relation_negated",
                severity="medium",
                confidence=0.7,
                chapter=chapter,
                snippet=sentence,
                location_note=None,
                evidence_status="sufficient",
                evidence=(
                    Evidence(
                        "manuscript", "当前正文片段", sentence, chapter.id, chapter.revision, None
                    ),
                    Evidence(
                        "relation",
                        f"{relation.from_name}是{relation.to_name}的{kind}",
                        relation.evidence_quote,
                        relation.source_chapter_id,
                        relation.source_revision,
                        relation.id,
                    ),
                ),
                refs=(
                    RelatedRef(
                        "relation",
                        relation.id,
                        f"{relation.from_name}→{relation.to_name} {kind}",
                    ),
                ),
                action="正文疑似否定了一条已记录的人物关系。这里只对照这条关系，不下主观结论。",
                key=f"character.relation_negated|{relation.id}|{chapter.id}|{hit}",
                insufficient=False,
            )


def _foreshadowing(
    found: list[QualityFinding],
    rows: tuple[ForeshadowMaterial, ...],
    chapters: tuple[ChapterMaterial, ...],
    by_id: dict[str, ChapterMaterial],
    focus: str | None,
) -> None:
    if not chapters:
        return
    latest = max(chapters, key=lambda item: item.reading_index)
    corpus = "\n".join(item.text for item in chapters)
    for row in rows:
        introduced = by_id.get(row.introduced_chapter_id)
        if introduced is None:
            continue
        payoff = by_id.get(row.payoff_chapter_id) if row.payoff_chapter_id else None
        if row.status in {"open", "planned"} and payoff is not None:
            passed = any(item.reading_index > payoff.reading_index for item in chapters)
            if passed and (focus is None or focus in {payoff.id, introduced.id, latest.id}):
                quote = (row.evidence_quote or "").strip()
                snippet = quote if quote and quote in payoff.text else ""
                _add(
                    found,
                    issue_type="foreshadowing",
                    rule_id="foreshadow.payoff_passed",
                    severity="medium",
                    confidence=0.66,
                    chapter=payoff,
                    snippet=snippet,
                    location_note=(
                        f"计划在《{payoff.title}》回收的伏笔仍是{row.status}，"
                        f"而《{latest.title}》已经排在它后面。"
                    ),
                    evidence_status="sufficient",
                    evidence=(
                        Evidence(
                            "foreshadowing",
                            row.description,
                            row.evidence_quote,
                            introduced.id,
                            None,
                            row.id,
                        ),
                    ),
                    refs=(RelatedRef("foreshadowing", row.id, row.description),),
                    action="计划回收的章节已经过去，伏笔仍未标成回收。请作者决定是补回收、改计划，还是保持原样。",
                    key=f"foreshadow.payoff_passed|{row.id}",
                    insufficient=False,
                )
        if (
            row.status == "open"
            and payoff is None
            and latest.reading_index - introduced.reading_index >= _LONG_OPEN_GAP
            and (focus is None or focus in {introduced.id, latest.id})
        ):
            _add(
                found,
                issue_type="foreshadowing",
                rule_id="foreshadow.long_open",
                severity="low",
                confidence=0.5,
                chapter=introduced,
                snippet=(row.evidence_quote or "")
                if (row.evidence_quote or "") in introduced.text
                else "",
                location_note=(
                    f"「{row.description}」从《{introduced.title}》埋下后，"
                    f"已经过了至少 {_LONG_OPEN_GAP} 章仍未指定回收。"
                ),
                evidence_status="sufficient",
                evidence=(
                    Evidence(
                        "foreshadowing",
                        row.description,
                        row.evidence_quote,
                        introduced.id,
                        None,
                        row.id,
                    ),
                ),
                refs=(RelatedRef("foreshadowing", row.id, row.description),),
                action="这只是长期未回收的提醒，不是断定剧情有错。",
                key=f"foreshadow.long_open|{row.id}",
                insufficient=False,
            )
        quote = (row.evidence_quote or "").strip()
        if row.status == "resolved" and quote and quote not in corpus:
            if focus is not None and focus != introduced.id:
                continue
            _add(
                found,
                issue_type="foreshadowing",
                rule_id="foreshadow.resolved_quote_missing",
                severity="low",
                confidence=0.6,
                chapter=introduced,
                snippet="",
                location_note="伏笔已标为回收，但证据原文不在任何章节正文里。",
                evidence_status="sufficient",
                evidence=(
                    Evidence("foreshadowing", row.description, quote, introduced.id, None, row.id),
                    Evidence("note", "正文中没有这段证据原文", None, None, None, None),
                ),
                refs=(RelatedRef("foreshadowing", row.id, row.description),),
                action="状态和正文可能不一致。请核对是证据抄错了，还是回收发生在没有留下原文的地方。",
                key=f"foreshadow.resolved_quote_missing|{row.id}",
                insufficient=False,
            )


def _outlines(
    found: list[QualityFinding],
    outlines: tuple[OutlineMaterial, ...],
    by_id: dict[str, ChapterMaterial],
    focus: str | None,
) -> None:
    for outline in outlines:
        chapter = by_id.get(outline.chapter_id)
        if chapter is None or (focus is not None and chapter.id != focus):
            continue
        _coverage(
            found,
            chapter,
            ref_id=outline.id,
            ref_kind="outline",
            required="\n".join(
                part for part in (outline.required_events, outline.must_advance) if part
            ),
            rule_missing="outline.required_missing",
        )
        _leaks(
            found,
            chapter,
            ref_id=outline.id,
            ref_kind="outline",
            secret=outline.forbidden_reveals,
            rule_id="outline.forbidden_leak",
        )


def _scenes(
    found: list[QualityFinding],
    scenes: tuple[SceneMaterial, ...],
    by_id: dict[str, ChapterMaterial],
    focus: str | None,
) -> None:
    for scene in scenes:
        chapter = by_id.get(scene.chapter_id)
        if chapter is None or (focus is not None and chapter.id != focus):
            continue
        _coverage(
            found,
            chapter,
            ref_id=scene.id,
            ref_kind="scene",
            required=scene.must_convey,
            rule_missing="outline.scene_missing",
        )
        _leaks(
            found,
            chapter,
            ref_id=scene.id,
            ref_kind="scene",
            secret=scene.must_not_reveal,
            rule_id="outline.scene_leak",
        )


def _coverage(
    found: list[QualityFinding],
    chapter: ChapterMaterial,
    *,
    ref_id: str,
    ref_kind: str,
    required: str | None,
    rule_missing: str,
) -> None:
    text = (required or "").strip()
    if text == "":
        return
    phrases = _phrases(text, 4)
    if not phrases:
        _add(
            found,
            issue_type="outline_execution",
            rule_id=f"{rule_missing}.undetermined",
            severity="low",
            confidence=0.3,
            chapter=chapter,
            snippet="",
            location_note="已确认大纲写了必须覆盖的内容，但表述过短，无法在正文里定位。",
            evidence_status="insufficient",
            evidence=(Evidence(ref_kind, "大纲要求", text, chapter.id, None, ref_id),),
            refs=(RelatedRef(ref_kind, ref_id, text[:80]),),
            action="无法判断正文有没有覆盖这条大纲。",
            key=f"{rule_missing}.undetermined|{ref_id}",
            insufficient=True,
        )
        return
    for phrase in phrases[:5]:
        if phrase in chapter.text:
            continue
        _add(
            found,
            issue_type="outline_execution",
            rule_id=rule_missing,
            severity="medium",
            confidence=0.58,
            chapter=chapter,
            snippet="",
            location_note=f"已确认大纲要求出现「{phrase}」，当前正文里没有这句表述。",
            evidence_status="sufficient",
            evidence=(
                Evidence(ref_kind, "大纲要求", phrase, chapter.id, None, ref_id),
                Evidence("note", "正文中未找到该表述", None, chapter.id, chapter.revision, None),
            ),
            refs=(RelatedRef(ref_kind, ref_id, phrase),),
            action="疑似尚未覆盖已确认大纲。正文可以故意不写，这不是逻辑错误结论。",
            key=f"{rule_missing}|{ref_id}|{phrase}",
            insufficient=False,
        )


def _leaks(
    found: list[QualityFinding],
    chapter: ChapterMaterial,
    *,
    ref_id: str,
    ref_kind: str,
    secret: str | None,
    rule_id: str,
) -> None:
    for phrase in _phrases(secret, 2)[:5]:
        if phrase not in chapter.text:
            continue
        sentence = _sentence_with(chapter.text, phrase)
        _add(
            found,
            issue_type="outline_execution",
            rule_id=rule_id,
            severity="high",
            confidence=0.77,
            chapter=chapter,
            snippet=sentence,
            location_note=None,
            evidence_status="sufficient",
            evidence=(
                Evidence(
                    "manuscript", "当前正文片段", sentence, chapter.id, chapter.revision, None
                ),
                Evidence(ref_kind, "禁止揭露", phrase, chapter.id, None, ref_id),
            ),
            refs=(RelatedRef(ref_kind, ref_id, phrase),),
            action="正文里出现了已确认大纲标明暂不揭露的表述。请作者决定是否提前说了。",
            key=f"{rule_id}|{ref_id}|{phrase}",
            insufficient=False,
        )


def _surface(
    found: list[QualityFinding],
    chapters: tuple[ChapterMaterial, ...],
    entities: tuple[EntityMaterial, ...],
    focus: str | None,
) -> None:
    names: dict[str, EntityMaterial] = {}
    for entity in entities:
        names[entity.name] = entity
        for alias in entity.aliases:
            names.setdefault(alias, entity)
    for chapter in _scoped(chapters, focus):
        seen_paragraphs: set[str] = set()
        for paragraph in chapter.text.split("\n\n"):
            cleaned = paragraph.strip()
            if len(cleaned) < 8:
                continue
            if cleaned in seen_paragraphs:
                _add(
                    found,
                    issue_type="text_surface",
                    rule_id="text.repeated_paragraph",
                    severity="low",
                    confidence=0.9,
                    chapter=chapter,
                    snippet=cleaned,
                    location_note="同一章里有两段相同文字。",
                    evidence_status="sufficient",
                    evidence=(
                        Evidence(
                            "manuscript", "重复段落", cleaned, chapter.id, chapter.revision, None
                        ),
                    ),
                    refs=(),
                    action="疑似重复段落。可能是故意的反复，请作者决定要不要删掉一处。",
                    key=f"text.repeated_paragraph|{chapter.id}|{cleaned}",
                    insufficient=False,
                )
            seen_paragraphs.add(cleaned)
        for match in _PUNCT.finditer(chapter.text):
            start = max(0, match.start() - 8)
            end = min(len(chapter.text), match.end() + 8)
            snippet = chapter.text[start:end].strip()
            _add(
                found,
                issue_type="text_surface",
                rule_id="text.repeated_punctuation",
                severity="low",
                confidence=0.84,
                chapter=chapter,
                snippet=snippet or match.group(0),
                location_note=None,
                evidence_status="sufficient",
                evidence=(
                    Evidence(
                        "manuscript",
                        "重复标点",
                        snippet or match.group(0),
                        chapter.id,
                        chapter.revision,
                        None,
                    ),
                ),
                refs=(),
                action="这里有连续的重复标点。这不是对文笔的评价。",
                key=f"text.repeated_punctuation|{chapter.id}|{match.start()}|{match.group(0)}",
                insufficient=False,
            )
        for match in _CALLED.finditer(chapter.text):
            subject = match.group(1)
            called = match.group(2)
            known = names.get(subject)
            if known is None:
                continue
            allowed = {known.name, *known.aliases}
            if called in allowed:
                continue
            sentence = _sentence_with(chapter.text, match.group(0))
            _add(
                found,
                issue_type="text_surface",
                rule_id="text.name_mismatch",
                severity="medium",
                confidence=0.73,
                chapter=chapter,
                snippet=sentence,
                location_note=f"设定中的名称是「{known.name}」，正文写成了「{called}」。",
                evidence_status="sufficient",
                evidence=(
                    Evidence(
                        "manuscript", "当前正文片段", sentence, chapter.id, chapter.revision, None
                    ),
                    Evidence(
                        "entity",
                        known.name,
                        "、".join(known.aliases) if known.aliases else known.name,
                        None,
                        None,
                        known.id,
                    ),
                ),
                refs=(RelatedRef("entity", known.id, known.name),),
                action="疑似名称或称谓和已记录的名字、别名不一致。别名里有的叫法不会报。",
                key=f"text.name_mismatch|{known.id}|{chapter.id}|{called}",
                insufficient=False,
            )


def _model_item(
    item: dict[str, object],
    chapter: ChapterMaterial,
    known_quotes: dict[str, Evidence],
) -> QualityFinding | None:
    issue_type = item.get("issue_type")
    snippet = item.get("manuscript_snippet")
    severity = item.get("severity")
    if not isinstance(issue_type, str) or issue_type not in _ISSUE_TYPES:
        return None
    if not isinstance(snippet, str) or snippet.strip() == "" or snippet.strip() not in chapter.text:
        return None
    if not isinstance(severity, str) or severity not in _SEVERITIES:
        return None
    confidence = item.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return None
    number = float(confidence)
    if number < 0 or number > 1:
        return None
    quote = item.get("source_quote")
    quote_text = quote.strip() if isinstance(quote, str) else ""
    known = known_quotes.get(quote_text)
    insufficient = known is None
    action = item.get("suggested_action")
    text = action.strip() if isinstance(action, str) else ""
    for banned in _BANNED_CLAIMS:
        text = text.replace(banned, "疑似不一致")
    if insufficient and "证据不足" not in text:
        text = f"{text} 证据不足。模型没有给出能对上的来源引用。"
    snippet_text = snippet.strip()
    evidence = [
        Evidence(
            "manuscript", "模型指出的正文片段", snippet_text, chapter.id, chapter.revision, None
        )
    ]
    refs: list[RelatedRef] = []
    if known is not None:
        evidence.append(known)
        if known.ref_id:
            refs.append(RelatedRef(known.kind, known.ref_id, known.label))
    else:
        evidence.append(
            Evidence("note", "没有对上已确认引用", quote_text or None, None, None, None)
        )
    return QualityFinding(
        issue_type=issue_type,
        rule_id="model.suspected",
        severity=severity,
        confidence=round(number, 2),
        chapter_id=chapter.id,
        manuscript_snippet=snippet_text[:500],
        target_revision=chapter.revision,
        location_note="来自单独启用的模型检查。规则检查没有被它替换。",
        evidence_status="insufficient" if insufficient else "sufficient",
        evidence=tuple(evidence),
        related_refs=tuple(refs),
        suggested_action=_action(text or "请作者对照材料判断。", insufficient=insufficient),
        fingerprint_key=f"model.suspected|{chapter.id}|{issue_type}|{snippet_text[:180]}",
        reading_index=chapter.reading_index,
    )


def _add(
    found: list[QualityFinding],
    *,
    issue_type: str,
    rule_id: str,
    severity: str,
    confidence: float,
    chapter: ChapterMaterial,
    snippet: str,
    location_note: str | None,
    evidence_status: str,
    evidence: tuple[Evidence, ...],
    refs: tuple[RelatedRef, ...],
    action: str,
    key: str,
    insufficient: bool,
) -> None:
    if any(item.fingerprint_key == key for item in found):
        return
    cleaned = snippet.strip()[:500]
    if evidence_status == "insufficient" and not cleaned and not evidence:
        return
    found.append(
        QualityFinding(
            issue_type=issue_type,
            rule_id=rule_id,
            severity=severity if severity in _SEVERITIES else "medium",
            confidence=min(1.0, max(0.0, round(confidence, 2))),
            chapter_id=chapter.id,
            manuscript_snippet=cleaned,
            target_revision=chapter.revision,
            location_note=location_note,
            evidence_status=evidence_status,
            evidence=evidence,
            related_refs=refs,
            suggested_action=_action(action, insufficient=insufficient),
            fingerprint_key=key,
            reading_index=chapter.reading_index,
        )
    )


def _action(text: str, *, insufficient: bool) -> str:
    body = text.strip()
    if insufficient and "证据不足" not in body:
        body = f"{body}证据不足。"
    if _NO_AUTO not in body:
        body = f"{body}{_NO_AUTO}"
    for banned in _BANNED_CLAIMS:
        body = body.replace(banned, "疑似不一致")
    return body[:800]


def _scoped(
    chapters: tuple[ChapterMaterial, ...],
    focus: str | None,
) -> tuple[ChapterMaterial, ...]:
    if focus is None:
        return chapters
    return tuple(item for item in chapters if item.id == focus)


def _phrases(text: str | None, min_len: int) -> list[str]:
    if text is None:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[、，,；;\n]+", text):
        cleaned = part.strip()
        if len(cleaned) < min_len or cleaned in seen:
            continue
        seen.add(cleaned)
        found.append(cleaned)
    return found


def _sentence_with(text: str, needle: str) -> str:
    for part in re.split(r"(?<=[。！？\n])", text):
        if needle in part and part.strip():
            return part.strip()[:500]
    return needle[:500]


def _share(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    first = {item.strip() for item in left if item.strip()}
    second = {item.strip() for item in right if item.strip()}
    return bool(first & second)


def _interval_kind(
    a_from: str | None,
    a_until: str | None,
    b_from: str | None,
    b_until: str | None,
) -> Literal["incomplete", "separate", "overlap", "undetermined"]:
    bounds = (a_from, a_until, b_from, b_until)
    if any(item is None or item.strip() == "" for item in bounds):
        return "incomplete"
    assert a_from is not None and a_until is not None
    assert b_from is not None and b_until is not None
    points = (
        _parse_point(a_from),
        _parse_point(a_until),
        _parse_point(b_from),
        _parse_point(b_until),
    )
    parsed = [point for point in points if point is not None]
    if len(parsed) == 4:
        scales = {point.scale for point in parsed}
        if len(scales) == 1 and _overlaps(parsed[0], parsed[1], parsed[2], parsed[3]):
            return "overlap"
        if len(scales) == 1:
            return "separate"
    if a_from.strip() == b_from.strip() and a_until.strip() == b_until.strip():
        return "overlap"
    return "undetermined"


def _order_kind(early: str | None, late: str | None) -> Literal["ok", "reversed", "undetermined"]:
    early_text = (early or "").strip()
    late_text = (late or "").strip()
    early_point = _parse_point(early_text)
    late_point = _parse_point(late_text)
    if early_point is not None and late_point is not None and early_point.scale == late_point.scale:
        if early_point.value > late_point.value:
            return "reversed"
        return "ok"
    if _TIME_HINT.search(early_text) or _TIME_HINT.search(late_text):
        return "undetermined"
    return "ok"


def _parse_point(text: str) -> _Point | None:
    cleaned = text.strip()
    if cleaned == "":
        return None
    matched = _DATE.search(cleaned) or _CN_DATE.search(cleaned)
    if matched is not None:
        year = int(matched.group(1))
        month = int(matched.group(2))
        day = int(matched.group(3))
        return _Point("date", year * 10_000 + month * 100 + day)
    matched = _DAY.search(cleaned)
    if matched is not None:
        return _Point("day", int(matched.group(1)))
    matched = _CHAPTER_TIME.search(cleaned)
    if matched is not None:
        return _Point("chapter", int(matched.group(1)))
    return None


def _overlaps(a0: _Point, a1: _Point, b0: _Point, b1: _Point) -> bool:
    left = max(min(a0.value, a1.value), min(b0.value, b1.value))
    right = min(max(a0.value, a1.value), max(b0.value, b1.value))
    return left <= right


def _later_state(
    left: StateMaterial,
    right: StateMaterial,
    by_id: dict[str, ChapterMaterial],
) -> StateMaterial:
    left_index = by_id[left.chapter_id].reading_index if left.chapter_id in by_id else -1
    right_index = by_id[right.chapter_id].reading_index if right.chapter_id in by_id else -1
    if right_index > left_index:
        return right
    if left_index > right_index:
        return left
    return right if right.id > left.id else left


def _by_reading(
    left_chapter: ChapterMaterial,
    right_chapter: ChapterMaterial,
    left: EventMaterial,
    right: EventMaterial,
) -> tuple[ChapterMaterial, ChapterMaterial, EventMaterial, EventMaterial]:
    if left_chapter.reading_index <= right_chapter.reading_index:
        return left_chapter, right_chapter, left, right
    return right_chapter, left_chapter, right, left


def _state_evidence(state: StateMaterial, label: str, value: str) -> Evidence:
    return Evidence(
        "entity_state",
        f"{state.entity_name}的{label}：{value}",
        state.evidence_quote,
        state.chapter_id,
        state.source_revision,
        state.id,
    )


def _chapters(value: object) -> tuple[ChapterMaterial, ...]:
    rows: list[ChapterMaterial] = []
    for item in _rows(value):
        chapter = _chapter(item)
        if chapter is not None:
            rows.append(chapter)
    return tuple(rows)


def _chapter(value: object) -> ChapterMaterial | None:
    if not isinstance(value, dict):
        return None
    chapter_id = _optional_str(value.get("id"))
    if chapter_id is None:
        return None
    index = value.get("reading_index")
    revision = value.get("revision")
    reading = index if isinstance(index, int) and not isinstance(index, bool) else 0
    rev = revision if isinstance(revision, int) and not isinstance(revision, bool) else 1
    return ChapterMaterial(
        id=chapter_id,
        title=_optional_str(value.get("title")) or chapter_id,
        reading_index=reading,
        revision=rev,
        text=_optional_str(value.get("text")) or "",
    )


def _events(value: object) -> tuple[EventMaterial, ...]:
    rows: list[EventMaterial] = []
    for item in _rows(value):
        if not isinstance(item, dict):
            continue
        event_id = _optional_str(item.get("id"))
        chapter_id = _optional_str(item.get("chapter_id"))
        if event_id is None or chapter_id is None:
            continue
        participants = item.get("participants")
        names = (
            tuple(part.strip() for part in participants if isinstance(part, str) and part.strip())
            if isinstance(participants, list)
            else ()
        )
        revision = item.get("source_revision")
        rows.append(
            EventMaterial(
                id=event_id,
                chapter_id=chapter_id,
                description=_optional_str(item.get("description")) or "",
                evidence_quote=_optional_str(item.get("evidence_quote")) or "",
                event_time_text=_optional_str(item.get("event_time_text")),
                participants=names,
                source_revision=revision
                if isinstance(revision, int) and not isinstance(revision, bool)
                else None,
            )
        )
    return tuple(rows)


def _states(value: object) -> tuple[StateMaterial, ...]:
    rows: list[StateMaterial] = []
    for item in _rows(value):
        if not isinstance(item, dict):
            continue
        state_id = _optional_str(item.get("id"))
        entity_id = _optional_str(item.get("entity_id"))
        chapter_id = _optional_str(item.get("chapter_id"))
        if state_id is None or entity_id is None or chapter_id is None:
            continue
        raw_values = item.get("values")
        values: list[tuple[str, str]] = []
        if isinstance(raw_values, dict):
            for key, raw in raw_values.items():
                if isinstance(key, str) and isinstance(raw, str):
                    values.append((key, raw))
        revision = item.get("source_revision")
        rows.append(
            StateMaterial(
                id=state_id,
                entity_id=entity_id,
                entity_name=_optional_str(item.get("entity_name")) or entity_id,
                chapter_id=chapter_id,
                values=tuple(values),
                evidence_quote=_optional_str(item.get("evidence_quote")),
                valid_from_text=_optional_str(item.get("valid_from_text")),
                valid_until_text=_optional_str(item.get("valid_until_text")),
                source_revision=revision
                if isinstance(revision, int) and not isinstance(revision, bool)
                else None,
            )
        )
    return tuple(rows)


def _relations_in(value: object) -> tuple[RelationMaterial, ...]:
    rows: list[RelationMaterial] = []
    for item in _rows(value):
        if not isinstance(item, dict):
            continue
        relation_id = _optional_str(item.get("id"))
        if relation_id is None:
            continue
        revision = item.get("source_revision")
        rows.append(
            RelationMaterial(
                id=relation_id,
                from_name=_optional_str(item.get("from_name")) or "",
                to_name=_optional_str(item.get("to_name")) or "",
                relation_type=_optional_str(item.get("relation_type")) or "",
                evidence_quote=_optional_str(item.get("evidence_quote")),
                source_chapter_id=_optional_str(item.get("source_chapter_id")),
                source_revision=revision
                if isinstance(revision, int) and not isinstance(revision, bool)
                else None,
            )
        )
    return tuple(rows)


def _outlines_in(value: object) -> tuple[OutlineMaterial, ...]:
    rows: list[OutlineMaterial] = []
    for item in _rows(value):
        if not isinstance(item, dict):
            continue
        outline_id = _optional_str(item.get("id"))
        chapter_id = _optional_str(item.get("chapter_id"))
        if outline_id is None or chapter_id is None:
            continue
        rows.append(
            OutlineMaterial(
                id=outline_id,
                chapter_id=chapter_id,
                required_events=_optional_str(item.get("required_events")),
                must_advance=_optional_str(item.get("must_advance")),
                forbidden_reveals=_optional_str(item.get("forbidden_reveals")),
            )
        )
    return tuple(rows)


def _scenes_in(value: object) -> tuple[SceneMaterial, ...]:
    rows: list[SceneMaterial] = []
    for item in _rows(value):
        if not isinstance(item, dict):
            continue
        scene_id = _optional_str(item.get("id"))
        chapter_id = _optional_str(item.get("chapter_id"))
        if scene_id is None or chapter_id is None:
            continue
        rows.append(
            SceneMaterial(
                id=scene_id,
                chapter_id=chapter_id,
                must_convey=_optional_str(item.get("must_convey")),
                must_not_reveal=_optional_str(item.get("must_not_reveal")),
            )
        )
    return tuple(rows)


def _foreshadow_in(value: object) -> tuple[ForeshadowMaterial, ...]:
    rows: list[ForeshadowMaterial] = []
    for item in _rows(value):
        if not isinstance(item, dict):
            continue
        row_id = _optional_str(item.get("id"))
        introduced = _optional_str(item.get("introduced_chapter_id"))
        if row_id is None or introduced is None:
            continue
        rows.append(
            ForeshadowMaterial(
                id=row_id,
                description=_optional_str(item.get("description")) or "",
                status=_optional_str(item.get("status")) or "open",
                introduced_chapter_id=introduced,
                payoff_chapter_id=_optional_str(item.get("payoff_chapter_id")),
                evidence_quote=_optional_str(item.get("evidence_quote")),
            )
        )
    return tuple(rows)


def _entities(value: object) -> tuple[EntityMaterial, ...]:
    rows: list[EntityMaterial] = []
    for item in _rows(value):
        if not isinstance(item, dict):
            continue
        entity_id = _optional_str(item.get("id"))
        name = _optional_str(item.get("name"))
        if entity_id is None or name is None:
            continue
        aliases = item.get("aliases")
        rows.append(
            EntityMaterial(
                id=entity_id,
                name=name,
                aliases=tuple(
                    alias.strip() for alias in aliases if isinstance(alias, str) and alias.strip()
                )
                if isinstance(aliases, list)
                else (),
            )
        )
    return tuple(rows)


def _rows(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    return []


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
