"""Guided ideation, world design, and character design.

Answers and generated candidates are stored apart from the manuscript and the
formal bible. Accept is the only path that writes novel metadata, entities,
relations, or draft plans.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.gateway import (
    enabled_default,
    endpoint_from_config,
    latest_enabled,
    load_enabled_config,
)
from app.ai.provider import ProviderError
from app.core.errors import (
    InvalidReference,
    ModelConfigInvalid,
    ModelNotConfigured,
    NotFound,
    ProviderRequestFailed,
    TaskStateError,
)
from app.core.redaction import redact_text
from app.models.catalog import Chapter, Novel
from app.models.ideation import IdeationCandidate, IdeationSession
from app.models.memory import EntityRelation, StoryEntity
from app.models.planning import StoryArc, StoryPlan
from app.repositories import catalog as catalog_repo
from app.schemas.ideation import (
    CandidateKind,
    CandidateStatus,
    IdeationAccept,
    IdeationAnswer,
    IdeationAnswerCreate,
    IdeationCandidateResponse,
    IdeationChoice,
    IdeationDecisionResponse,
    IdeationGenerateResponse,
    IdeationKind,
    IdeationQuestion,
    IdeationSessionCreate,
    IdeationSessionResponse,
    IdeationStatus,
    ProviderMode,
)
from app.services.memory import (
    _ensure_unique_name,
    _public_provider_error,
    generate_analysis_text,
)

logger = logging.getLogger("app.ideation")

_WORLD_TYPES = frozenset({"rule", "location", "organization"})
_OPEN = frozenset({"pending", "deferred"})


@dataclass(frozen=True)
class _Choice:
    id: str
    label: str


@dataclass(frozen=True)
class _Question:
    id: str
    prompt: str
    help_text: str
    optional: bool = False
    choices: tuple[_Choice, ...] = ()


@dataclass(frozen=True)
class _Draft:
    candidate_kind: str
    title: str
    payload: dict[str, object]


_GUIDED: tuple[_Question, ...] = (
    _Question(
        id="basis",
        prompt="从哪里开始？",
        help_text="可以从零开始，也可以顺着这本作品里已经写下的设定。",
        choices=(
            _Choice("scratch", "从零开始"),
            _Choice("existing", "顺着已有设定"),
        ),
    ),
    _Question(
        id="desire",
        prompt="你希望读者读完记住什么，或这本小说靠近哪种感觉？",
        help_text="一句话就够。还不确定可以写「还没想好」。",
    ),
    _Question(
        id="pressure",
        prompt="核心处境或冲突的种子是什么？",
        help_text="可以很模糊，例如谁被什么卡住。",
    ),
    _Question(
        id="boundary",
        prompt="不想写成什么样？题材或调性上有什么边界？",
        help_text="没有边界就写「没有特别限制」。",
    ),
)
_WORLD: tuple[_Question, ...] = (
    _Question(
        id="focus",
        prompt="这次想补哪一类世界设定？",
        help_text="会连同已有圣经条目一起交给模型。确认前不会新建正式设定。",
        choices=(
            _Choice("rule", "世界规则"),
            _Choice("location", "地点"),
            _Choice("organization", "势力"),
            _Choice("all", "都要一些"),
        ),
    ),
    _Question(
        id="hint",
        prompt="有什么必须守住，或想顺着展开的提示？",
        help_text="可以留空。",
        optional=True,
    ),
)
_CHARACTER: tuple[_Question, ...] = (
    _Question(
        id="focus",
        prompt="这次想设计谁？",
        help_text="会连同已有人物、关系和故事线一起交给模型。确认前不会写入正式人物。",
        choices=(
            _Choice("protagonist", "主角"),
            _Choice("supporting", "重要配角"),
            _Choice("relation", "一段关系"),
            _Choice("arc", "一条人物弧线"),
        ),
    ),
    _Question(
        id="hint",
        prompt="这个人或这段关系要守住什么？",
        help_text="可以留空。",
        optional=True,
    ),
)
_QUESTIONS = {"guided": _GUIDED, "world": _WORLD, "character": _CHARACTER}
_PROMPT_VERSION = {
    "guided": "guided_ideation_v1",
    "world": "world_design_v1",
    "character": "character_design_v1",
}
_ALLOWED = {
    "guided": frozenset({"work_direction"}),
    "world": frozenset({"world_setting"}),
    "character": frozenset({"character_card", "character_relation", "character_arc"}),
}
_ROLE = {
    "protagonist": "主角",
    "supporting": "重要配角",
    "relation": "关系里的人",
    "arc": "弧线中心",
}


def list_sessions(session: Session, novel_id: str) -> list[IdeationSessionResponse]:
    _require_novel(session, novel_id)
    rows = session.scalars(
        select(IdeationSession)
        .where(IdeationSession.novel_id == novel_id)
        .order_by(IdeationSession.created_at.desc(), IdeationSession.id.asc())
    ).all()
    return [_session_response(session, row) for row in rows]


def create_session(
    session: Session,
    novel_id: str,
    payload: IdeationSessionCreate,
) -> IdeationSessionResponse:
    _require_novel(session, novel_id)
    mode, model_name, config_id = _resolve_model(session, payload)
    now = _now()
    row = IdeationSession(
        id=_new_id(),
        novel_id=novel_id,
        kind=payload.kind,
        status="collecting",
        step_index=0,
        answers=[],
        model_config_id=config_id,
        provider_mode=mode,
        model_name=model_name,
        prompt_version=_PROMPT_VERSION[payload.kind],
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    _commit(session)
    session.refresh(row)
    logger.info("ideation session created")
    return _session_response(session, row)


def get_session(session: Session, session_id: str) -> IdeationSessionResponse:
    row = _require_session(session, session_id)
    return _session_response(session, row)


def answer_session(
    session: Session,
    session_id: str,
    payload: IdeationAnswerCreate,
) -> IdeationSessionResponse:
    row = _require_session(session, session_id)
    before = _manuscript_snapshot(session, row.novel_id)
    questions = _QUESTIONS[row.kind]
    if row.step_index >= len(questions):
        raise InvalidReference("这些问题已经答完。")
    question = questions[row.step_index]
    if payload.question_id != question.id:
        raise InvalidReference("请先回答当前这个问题。")
    answer = redact_text(payload.answer).strip()
    if question.choices and answer not in {item.id for item in question.choices}:
        raise InvalidReference("请先选择一项。")
    if not question.choices and not question.optional and answer == "":
        raise InvalidReference("请先写下回答。")
    stored = _answers(row.answers)
    stored.append({"question_id": question.id, "prompt": question.prompt, "answer": answer})
    row.answers = cast(list[object], stored)
    row.step_index = len(stored)
    row.updated_at = _now()
    _commit_keeping_manuscript(session, row.novel_id, before)
    session.refresh(row)
    logger.info("ideation answer stored")
    return _session_response(session, row)


def generate_session(session: Session, session_id: str) -> IdeationGenerateResponse:
    row = _require_session(session, session_id)
    before = _manuscript_snapshot(session, row.novel_id)
    questions = _QUESTIONS[row.kind]
    answers = _answers(row.answers)
    if not _ready(questions, answers):
        raise InvalidReference("还要先回答完引导问题。正式资料和正文都没有改。")
    novel = _require_novel(session, row.novel_id)
    entities = _entities(session, row.novel_id)
    drafts = _drafts(session, row, novel, entities, answers)
    start = _next_sort(session, row.id)
    now = _now()
    created: list[IdeationCandidate] = []
    for offset, draft in enumerate(drafts):
        candidate = IdeationCandidate(
            id=_new_id(),
            session_id=row.id,
            novel_id=row.novel_id,
            candidate_kind=draft.candidate_kind,
            title=draft.title,
            payload=draft.payload,
            status="pending",
            sort_order=start + offset,
            review_note=None,
            applied=None,
            created_at=now,
            reviewed_at=None,
        )
        session.add(candidate)
        created.append(candidate)
    row.status = "generated"
    row.updated_at = now
    _commit_keeping_manuscript(session, row.novel_id, before)
    session.refresh(row)
    logger.info("ideation candidates stored")
    simulated = row.provider_mode == "mock"
    note = "模拟候选尚未写入正式资料或正文。" if simulated else "模型候选尚未写入正式资料或正文。"
    return IdeationGenerateResponse(
        session=_session_response(session, row),
        created_candidate_ids=[item.id for item in created],
        manuscript_changed=False,
        formal_material_changed=False,
        provider_mode="mock" if simulated else "openai_compatible",
        model_config_id=row.model_config_id,
        model_name=row.model_name,
        simulated=simulated,
        note=note,
    )


def accept_candidate(
    session: Session,
    candidate_id: str,
    payload: IdeationAccept,
) -> IdeationDecisionResponse:
    candidate = _require_candidate(session, candidate_id)
    if candidate.status not in _OPEN:
        raise TaskStateError("这份候选已经处理过。")
    parent = _require_session(session, candidate.session_id)
    before = _manuscript_snapshot(session, candidate.novel_id)
    source = payload.payload if payload.payload is not None else candidate.payload
    normalized = _normalize(candidate.candidate_kind, source, strict=True)
    if normalized is None:
        raise InvalidReference("这份候选没有可写入的内容。")
    applied = _apply(session, candidate.novel_id, candidate.candidate_kind, normalized)
    now = _now()
    candidate.payload = normalized
    candidate.status = "accepted"
    candidate.applied = applied
    candidate.reviewed_at = now
    parent.updated_at = now
    _commit_keeping_manuscript(session, candidate.novel_id, before)
    session.refresh(candidate)
    logger.info("ideation candidate accepted")
    return IdeationDecisionResponse(
        candidate=_candidate_response(parent, candidate),
        manuscript_changed=False,
        formal_material_changed=True,
    )


def reject_candidate(session: Session, candidate_id: str) -> IdeationDecisionResponse:
    return _close_candidate(session, candidate_id, "rejected", formal=False)


def defer_candidate(session: Session, candidate_id: str) -> IdeationDecisionResponse:
    candidate = _require_candidate(session, candidate_id)
    if candidate.status != "pending":
        raise TaskStateError("只有还没处理的候选可以延后。")
    return _close_candidate(session, candidate_id, "deferred", formal=False)


def _close_candidate(
    session: Session,
    candidate_id: str,
    status: str,
    *,
    formal: bool,
) -> IdeationDecisionResponse:
    candidate = _require_candidate(session, candidate_id)
    if candidate.status not in _OPEN:
        raise TaskStateError("这份候选已经处理过。")
    parent = _require_session(session, candidate.session_id)
    before = _manuscript_snapshot(session, candidate.novel_id)
    now = _now()
    candidate.status = status
    candidate.reviewed_at = now
    parent.updated_at = now
    _commit_keeping_manuscript(session, candidate.novel_id, before)
    session.refresh(candidate)
    logger.info("ideation candidate updated")
    return IdeationDecisionResponse(
        candidate=_candidate_response(parent, candidate),
        manuscript_changed=False,
        formal_material_changed=formal,
    )


def _apply(
    session: Session,
    novel_id: str,
    candidate_kind: str,
    payload: dict[str, object],
) -> dict[str, object]:
    if candidate_kind == "work_direction":
        return _apply_direction(session, novel_id, payload)
    if candidate_kind == "world_setting":
        return _apply_entity(session, novel_id, payload, aliases=[])
    if candidate_kind == "character_card":
        aliases = _string_list(payload.get("aliases"))
        return _apply_entity(session, novel_id, payload, aliases=aliases)
    if candidate_kind == "character_relation":
        return _apply_relation(session, novel_id, payload)
    if candidate_kind == "character_arc":
        return _apply_arc(session, novel_id, payload)
    raise InvalidReference("不认识这类候选。")


def _apply_direction(
    session: Session,
    novel_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    novel = _require_novel(session, novel_id)
    written: list[str] = []
    genre = _as_text(payload.get("genre"))
    if genre is not None:
        novel.genre = genre
        written.append("genre")
    tone = _as_text(payload.get("tone"))
    if tone is not None:
        novel.style_guide = tone
        written.append("style_guide")
    synopsis = _as_text(payload.get("synopsis"))
    if synopsis is not None:
        novel.synopsis = synopsis
        written.append("synopsis")
    conflict = _as_text(payload.get("core_conflict"))
    if conflict is not None:
        novel.core_conflict = conflict
        written.append("core_conflict")
    if written:
        novel.updated_at = _now()
    direction = _as_text(payload.get("direction"))
    plan_id: str | None = None
    if direction is not None:
        plan_id = _write_logline(session, novel_id, direction)
    if not written and plan_id is None:
        raise InvalidReference("这份候选没有可写入的作品信息。")
    return {"novel_fields": written, "story_plan_id": plan_id}


def _write_logline(session: Session, novel_id: str, direction: str) -> str:
    plan = session.scalars(select(StoryPlan).where(StoryPlan.novel_id == novel_id)).first()
    now = _now()
    if plan is None:
        plan = StoryPlan(
            id=_new_id(),
            novel_id=novel_id,
            logline=direction,
            body=None,
            ending_intent=None,
            status="draft",
            revision=1,
            created_at=now,
            updated_at=now,
        )
        session.add(plan)
        return plan.id
    if plan.logline != direction:
        plan.logline = direction
        if plan.status == "confirmed":
            plan.status = "draft"
        plan.revision += 1
        plan.updated_at = now
    return plan.id


def _apply_entity(
    session: Session,
    novel_id: str,
    payload: dict[str, object],
    *,
    aliases: list[str],
) -> dict[str, object]:
    name = _as_text(payload.get("name"))
    if name is None:
        raise InvalidReference("设定需要一个名字。")
    entity_type = payload.get("entity_type")
    if not isinstance(entity_type, str):
        raise InvalidReference("设定类型无法读取。")
    _ensure_unique_name(session, novel_id, name, exclude_id=None)
    now = _now()
    row = StoryEntity(
        id=_new_id(),
        novel_id=novel_id,
        entity_type=entity_type,
        name=name,
        aliases=aliases,
        profile=_profile_from(payload),
        status="active",
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session.add(row)
    return {"entity_id": row.id}


def _apply_relation(
    session: Session,
    novel_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    from_name = _as_text(payload.get("from_name"))
    to_name = _as_text(payload.get("to_name"))
    relation_type = _as_text(payload.get("relation_type"))
    if from_name is None or to_name is None or relation_type is None:
        raise InvalidReference("关系需要两端的名字和关系类型。")
    origin = _entity_by_name(session, novel_id, from_name)
    target = _entity_by_name(session, novel_id, to_name)
    if origin is None or target is None:
        raise InvalidReference("关系两端都得是这本作品里已经有的设定。这次没有写入关系。")
    if origin.id == target.id:
        raise InvalidReference("关系的两端不能是同一个设定。")
    now = _now()
    row = EntityRelation(
        id=_new_id(),
        novel_id=novel_id,
        from_entity_id=origin.id,
        to_entity_id=target.id,
        relation_type=relation_type,
        story_time_text=None,
        storyline=None,
        source_chapter_id=None,
        source_revision=None,
        evidence_quote=_as_text(payload.get("note")) or "作者确认的人物设计候选。",
        status="active",
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session.add(row)
    return {"relation_id": row.id, "from_entity_id": origin.id, "to_entity_id": target.id}


def _apply_arc(session: Session, novel_id: str, payload: dict[str, object]) -> dict[str, object]:
    title = _as_text(payload.get("title"))
    if title is None:
        raise InvalidReference("人物弧线需要一个标题。")
    now = _now()
    current = session.scalar(
        select(func.max(StoryArc.sort_order)).where(StoryArc.novel_id == novel_id)
    )
    sort_order = 0 if current is None else int(current) + 1
    row = StoryArc(
        id=_new_id(),
        novel_id=novel_id,
        arc_type="character",
        title=title,
        summary=_as_text(payload.get("summary")),
        thread_visibility=None,
        sort_order=sort_order,
        status="draft",
        revision=1,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    return {"story_arc_id": row.id, "status": "draft"}


def _drafts(
    session: Session,
    row: IdeationSession,
    novel: Novel,
    entities: list[StoryEntity],
    answers: list[dict[str, str]],
) -> list[_Draft]:
    if row.provider_mode == "mock":
        return _mock_drafts(row.kind, answers, entities)
    if row.model_config_id is None:
        raise ModelNotConfigured("这次引导固定的模型配置已经不在。")
    config = load_enabled_config(session, row.model_config_id)
    if config.provider_type == "mock":
        return _mock_drafts(row.kind, answers, entities)
    prompt = _prompt(row.kind, answers, _context_block(session, novel, entities))
    try:
        raw = generate_analysis_text(endpoint=endpoint_from_config(config), prompt=prompt)
    except ProviderError as exc:
        raise _public_provider_error(exc) from exc
    try:
        return _drafts_from_text(row.kind, raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderRequestFailed(
            "MODEL_BAD_RESPONSE",
            "模型没有返回可解析的创意候选。正式资料和正文没有改动。",
            502,
        ) from exc


def _resolve_model(session: Session, payload: IdeationSessionCreate) -> tuple[str, str, str | None]:
    if payload.model_config_id:
        config = load_enabled_config(session, payload.model_config_id)
        if payload.use_mock and config.provider_type != "mock":
            raise ModelConfigInvalid("模拟生成不能绑定外部模型。")
        if payload.use_mock or config.provider_type == "mock":
            return "mock", config.model_name, config.id
        return "openai_compatible", config.model_name, config.id
    if payload.use_mock:
        return "mock", "模拟模型", None
    default = enabled_default(session)
    if default is not None:
        if default.provider_type == "mock":
            return "mock", default.model_name, default.id
        return "openai_compatible", default.model_name, default.id
    found = latest_enabled(session, "openai_compatible")
    if found is None:
        raise ModelNotConfigured()
    return "openai_compatible", found.model_name, found.id


def _mock_drafts(
    kind: str,
    answers: list[dict[str, str]],
    entities: list[StoryEntity],
) -> list[_Draft]:
    by_id = {item["question_id"]: item["answer"] for item in answers}
    if kind == "guided":
        return _mock_guided(by_id, entities)
    if kind == "world":
        return _mock_world(by_id, entities)
    return _mock_character(by_id, entities)


def _mock_guided(by_id: dict[str, str], entities: list[StoryEntity]) -> list[_Draft]:
    basis = by_id.get("basis", "scratch")
    desire = by_id.get("desire") or "还没想好"
    pressure = by_id.get("pressure") or "有人被什么拦住"
    boundary = by_id.get("boundary") or "没有特别限制"
    lead = "顺着已有设定" if basis == "existing" else "从零开始"
    known = f"已有「{entities[0].name}」。" if basis == "existing" and entities else ""
    return [
        _Draft(
            "work_direction",
            "候选方向",
            {
                "direction": f"{lead}：{desire}"[:500],
                "genre": "寓言",
                "tone": boundary[:20000],
                "core_conflict": pressure[:20000],
                "synopsis": f"{known}{desire}"[:20000],
            },
        ),
        _Draft(
            "work_direction",
            "另一条方向",
            {
                "direction": "把冲突放到更小的日常里",
                "genre": "传奇",
                "tone": "冷一点",
                "core_conflict": "想离开的人被留下来",
                "synopsis": "另一条候选，确认前不是简介。",
            },
        ),
    ]


def _mock_world(by_id: dict[str, str], entities: list[StoryEntity]) -> list[_Draft]:
    focus = by_id.get("focus") or "all"
    hint = by_id.get("hint") or ""
    known = f"已有设定「{entities[0].name}」仍有效。" if entities else "还没有正式设定。"
    hint_line = f"作者提示：{hint}" if hint else "没有额外提示。"
    summary = f"{known}{hint_line}"
    catalog = {
        "rule": ("夜禁", "入夜后城门不再打开。"),
        "location": ("北门外", "城门外的空地。"),
        "organization": ("守门人", "负责夜里关门的一伙人。"),
    }
    selected = list(catalog) if focus == "all" else [focus] if focus in catalog else ["rule"]
    drafts: list[_Draft] = []
    for entity_type in selected:
        name, detail = catalog[entity_type]
        drafts.append(
            _Draft(
                "world_setting",
                name,
                {
                    "entity_type": entity_type,
                    "name": name,
                    "summary": summary[:4000],
                    "detail": detail,
                },
            )
        )
    return drafts


def _mock_character(by_id: dict[str, str], entities: list[StoryEntity]) -> list[_Draft]:
    focus = by_id.get("focus") or "protagonist"
    note = by_id.get("hint") or "作者还没有补充。"
    others = [item.name for item in entities if item.entity_type == "character"]
    target = others[0] if others else "阿芷"
    drafts = [_character_card("沈酌", _ROLE.get(focus, "人物"), note)]
    if not others:
        drafts.append(_character_card("阿芷", "重要配角", "和沈酌相对的人。"))
    drafts.append(
        _Draft(
            "character_relation",
            f"沈酌与{target}",
            {
                "from_name": "沈酌",
                "to_name": target,
                "relation_type": "亏欠",
                "note": note[:4000],
            },
        )
    )
    drafts.append(
        _Draft(
            "character_arc",
            "沈酌的选择",
            {
                "title": "沈酌的选择",
                "summary": f"沈酌想离开，又被{target}留下。{note}"[:4000],
            },
        )
    )
    return drafts


def _character_card(name: str, role: str, note: str) -> _Draft:
    return _Draft(
        "character_card",
        name,
        {
            "name": name,
            "aliases": [],
            "role": role,
            "desire": "想把话说完",
            "fear": "门再次关上",
            "note": note[:4000],
            "entity_type": "character",
        },
    )


def _prompt(kind: str, answers: list[dict[str, str]], context: str) -> str:
    lines = [
        "你是长篇小说的创作助手。只返回一个 JSON 对象，不要写 Markdown，不要写正文。",
        "这些结果是候选。作者确认之前，不能当成已经生效的设定。",
        "已有资料：",
        context or "（还没有正式设定）",
        "作者的回答：",
    ]
    for item in answers:
        lines.append(f"- {item['prompt']} {item['answer']}")
    lines.append(_schema_text(kind))
    lines.append("没有把握就少给几条。candidates 最多 4 条。不要把候选写成已经发生的正文事实。")
    return "\n".join(lines)


def _schema_text(kind: str) -> str:
    if kind == "guided":
        shape = (
            '{"candidates":[{"kind":"work_direction","title":"短标题","payload":'
            '{"direction":"一句话方向","genre":"题材","tone":"调性","core_conflict":"核心冲突",'
            '"synopsis":"简介"}}]}'
        )
    elif kind == "world":
        shape = (
            '{"candidates":[{"kind":"world_setting","title":"名称","payload":'
            '{"entity_type":"rule 或 location 或 organization","name":"名称",'
            '"summary":"一句说明","detail":"可空"}}]}'
        )
    else:
        shape = (
            '{"candidates":['
            '{"kind":"character_card","title":"人名","payload":{"name":"人名","aliases":[],'
            '"role":"身份","desire":"想要","fear":"害怕","note":"备注"}},'
            '{"kind":"character_relation","title":"关系","payload":{"from_name":"已有或本次人名",'
            '"to_name":"已有或本次人名","relation_type":"关系","note":"备注"}},'
            '{"kind":"character_arc","title":"弧线","payload":{"title":"标题","summary":"变化"}}'
            "]}"
        )
    return f"JSON 形状：{shape}"


def _drafts_from_text(kind: str, raw: str) -> list[_Draft]:
    parsed = _json_object(raw)
    raw_items = parsed.get("candidates")
    if not isinstance(raw_items, list):
        raise ValueError("candidates")
    allowed = _ALLOWED[kind]
    drafts: list[_Draft] = []
    for item in raw_items:
        if len(drafts) >= 4:
            break
        if not isinstance(item, dict):
            continue
        candidate_kind = item.get("kind")
        if not isinstance(candidate_kind, str) or candidate_kind not in allowed:
            continue
        payload = _normalize(candidate_kind, item.get("payload"), strict=False)
        if payload is None:
            continue
        drafts.append(_Draft(candidate_kind, _title(item.get("title"), payload), payload))
    if not drafts:
        raise ValueError("empty")
    return drafts


def _normalize(candidate_kind: str, payload: object, *, strict: bool) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return _reject(strict, "候选内容无法读取。")
    body = {str(key): value for key, value in payload.items()}
    if candidate_kind == "work_direction":
        return _normalize_direction(body, strict=strict)
    if candidate_kind == "world_setting":
        return _normalize_world(body, strict=strict)
    if candidate_kind == "character_card":
        return _normalize_card(body, strict=strict)
    if candidate_kind == "character_relation":
        return _normalize_relation(body, strict=strict)
    if candidate_kind == "character_arc":
        return _normalize_arc(body, strict=strict)
    return _reject(strict, "不认识这类候选。")


def _normalize_direction(payload: dict[str, object], *, strict: bool) -> dict[str, object] | None:
    fields = {
        "direction": _text_field(payload.get("direction"), 500, strict=strict),
        "genre": _text_field(payload.get("genre"), 100, strict=strict),
        "tone": _text_field(payload.get("tone"), 20000, strict=strict),
        "core_conflict": _text_field(payload.get("core_conflict"), 20000, strict=strict),
        "synopsis": _text_field(payload.get("synopsis"), 20000, strict=strict),
    }
    cleaned: dict[str, object] = {key: value for key, value in fields.items() if value is not None}
    if not cleaned:
        return _reject(strict, "这份候选没有可写入的作品信息。")
    return cleaned


def _normalize_world(payload: dict[str, object], *, strict: bool) -> dict[str, object] | None:
    entity_type = payload.get("entity_type")
    if not isinstance(entity_type, str) or entity_type not in _WORLD_TYPES:
        return _reject(strict, "世界设定只能是规则、地点或势力。")
    name = _text_field(payload.get("name"), 200, strict=strict)
    if name is None:
        return _reject(strict, "设定需要一个名字。")
    return {
        "entity_type": entity_type,
        "name": name,
        "summary": _text_field(payload.get("summary"), 4000, strict=strict) or "",
        "detail": _text_field(payload.get("detail"), 4000, strict=strict) or "",
    }


def _normalize_card(payload: dict[str, object], *, strict: bool) -> dict[str, object] | None:
    name = _text_field(payload.get("name"), 200, strict=strict)
    if name is None:
        return _reject(strict, "人物需要一个名字。")
    aliases = _alias_list(payload.get("aliases"), strict=strict)
    if aliases is None:
        return None
    return {
        "entity_type": "character",
        "name": name,
        "aliases": aliases,
        "role": _text_field(payload.get("role"), 200, strict=strict) or "",
        "desire": _text_field(payload.get("desire"), 1000, strict=strict) or "",
        "fear": _text_field(payload.get("fear"), 1000, strict=strict) or "",
        "note": _text_field(payload.get("note"), 4000, strict=strict) or "",
    }


def _normalize_relation(payload: dict[str, object], *, strict: bool) -> dict[str, object] | None:
    from_name = _text_field(payload.get("from_name"), 200, strict=strict)
    to_name = _text_field(payload.get("to_name"), 200, strict=strict)
    relation_type = _text_field(payload.get("relation_type"), 80, strict=strict)
    if from_name is None or to_name is None or relation_type is None:
        return _reject(strict, "关系需要两端的名字和关系类型。")
    return {
        "from_name": from_name,
        "to_name": to_name,
        "relation_type": relation_type,
        "note": _text_field(payload.get("note"), 4000, strict=strict) or "",
    }


def _normalize_arc(payload: dict[str, object], *, strict: bool) -> dict[str, object] | None:
    title = _text_field(payload.get("title"), 200, strict=strict)
    if title is None:
        return _reject(strict, "人物弧线需要一个标题。")
    return {
        "title": title,
        "summary": _text_field(payload.get("summary"), 4000, strict=strict) or "",
    }


def _context_block(session: Session, novel: Novel, entities: list[StoryEntity]) -> str:
    lines: list[str] = []
    if novel.title.strip():
        lines.append(f"书名：{novel.title.strip()}")
    if novel.genre and novel.genre.strip():
        lines.append(f"题材：{novel.genre.strip()}")
    if novel.core_conflict and novel.core_conflict.strip():
        lines.append(f"核心冲突：{novel.core_conflict.strip()}")
    if novel.synopsis and novel.synopsis.strip():
        lines.append(f"简介：{novel.synopsis.strip()[:500]}")
    if novel.style_guide and novel.style_guide.strip():
        lines.append(f"文风：{novel.style_guide.strip()[:500]}")
    plan = session.scalars(select(StoryPlan).where(StoryPlan.novel_id == novel.id)).first()
    if plan is not None and plan.logline:
        lines.append(f"已有方向：{plan.logline.strip()[:300]}")
    for entity in entities[:40]:
        summary = ""
        if isinstance(entity.profile, dict):
            raw = entity.profile.get("summary") or entity.profile.get("role") or ""
            if isinstance(raw, str):
                summary = raw.strip()[:80]
        lines.append(f"- {entity.entity_type} {entity.name} {summary}".rstrip())
    relations = session.scalars(
        select(EntityRelation)
        .where(EntityRelation.novel_id == novel.id, EntityRelation.deleted_at.is_(None))
        .order_by(EntityRelation.created_at.asc())
        .limit(20)
    ).all()
    names = {entity.id: entity.name for entity in entities}
    for relation in relations:
        left = names.get(relation.from_entity_id, "未知")
        right = names.get(relation.to_entity_id, "未知")
        lines.append(f"- 关系 {left} {relation.relation_type} {right}")
    arcs = session.scalars(
        select(StoryArc)
        .where(StoryArc.novel_id == novel.id)
        .order_by(StoryArc.sort_order.asc())
        .limit(10)
    ).all()
    for arc in arcs:
        lines.append(f"- 故事线 {arc.title}")
    text = "\n".join(lines).strip()
    return text[:6000]


def _session_response(session: Session, row: IdeationSession) -> IdeationSessionResponse:
    questions = _QUESTIONS[row.kind]
    answers = _answers(row.answers)
    current = questions[row.step_index] if row.step_index < len(questions) else None
    candidates = _candidate_rows(session, row.id)
    mode: ProviderMode = "mock" if row.provider_mode == "mock" else "openai_compatible"
    kind = cast(IdeationKind, row.kind if row.kind in _QUESTIONS else "guided")
    status = cast(
        IdeationStatus,
        row.status if row.status in {"collecting", "generated"} else "collecting",
    )
    return IdeationSessionResponse(
        id=row.id,
        novel_id=row.novel_id,
        kind=kind,
        status=status,
        step_index=row.step_index,
        answers=[IdeationAnswer(**item) for item in answers],
        questions=[_question_model(item) for item in questions],
        current_question=_question_model(current) if current is not None else None,
        ready_to_generate=_ready(questions, answers),
        model_config_id=row.model_config_id,
        provider_mode=mode,
        model_name=row.model_name,
        prompt_version=row.prompt_version,
        simulated=mode == "mock",
        candidates=[_candidate_response(row, item) for item in candidates],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _candidate_response(
    parent: IdeationSession,
    row: IdeationCandidate,
) -> IdeationCandidateResponse:
    allowed = _ALLOWED["character"] | _ALLOWED["guided"] | _ALLOWED["world"]
    kind = cast(
        CandidateKind,
        row.candidate_kind if row.candidate_kind in allowed else "work_direction",
    )
    status = cast(
        CandidateStatus,
        row.status if row.status in {"pending", "accepted", "rejected", "deferred"} else "pending",
    )
    return IdeationCandidateResponse(
        id=row.id,
        session_id=row.session_id,
        novel_id=row.novel_id,
        candidate_kind=kind,
        title=row.title,
        payload=_object_dict(row.payload),
        status=status,
        model_config_id=parent.model_config_id,
        model_name=parent.model_name,
        prompt_version=parent.prompt_version,
        applied=_object_dict(row.applied) if isinstance(row.applied, dict) else None,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _question_model(question: _Question) -> IdeationQuestion:
    return IdeationQuestion(
        id=question.id,
        prompt=question.prompt,
        help_text=question.help_text,
        optional=question.optional,
        choices=[IdeationChoice(id=item.id, label=item.label) for item in question.choices],
    )


def _ready(questions: tuple[_Question, ...], answers: list[dict[str, str]]) -> bool:
    answered = {item["question_id"] for item in answers}
    return all(question.id in answered for question in questions if not question.optional)


def _answers(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        question_id = item.get("question_id")
        prompt = item.get("prompt")
        answer = item.get("answer")
        if isinstance(question_id, str) and isinstance(answer, str):
            rows.append(
                {
                    "question_id": question_id,
                    "prompt": prompt if isinstance(prompt, str) else "",
                    "answer": answer,
                }
            )
    return rows


def _candidate_rows(session: Session, session_id: str) -> list[IdeationCandidate]:
    return list(
        session.scalars(
            select(IdeationCandidate)
            .where(IdeationCandidate.session_id == session_id)
            .order_by(IdeationCandidate.sort_order.asc(), IdeationCandidate.id.asc())
        ).all()
    )


def _entities(session: Session, novel_id: str) -> list[StoryEntity]:
    return list(
        session.scalars(
            select(StoryEntity)
            .where(StoryEntity.novel_id == novel_id, StoryEntity.deleted_at.is_(None))
            .order_by(StoryEntity.created_at.asc(), StoryEntity.id.asc())
        ).all()
    )


def _entity_by_name(session: Session, novel_id: str, name: str) -> StoryEntity | None:
    target = " ".join(name.strip().casefold().split())
    for entity in _entities(session, novel_id):
        if " ".join(entity.name.strip().casefold().split()) == target:
            return entity
    return None


def _next_sort(session: Session, session_id: str) -> int:
    current = session.scalar(
        select(func.max(IdeationCandidate.sort_order)).where(
            IdeationCandidate.session_id == session_id
        )
    )
    if current is None:
        return 0
    return int(current) + 1


def _manuscript_snapshot(session: Session, novel_id: str) -> tuple[tuple[object, ...], ...]:
    rows = session.scalars(
        select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.id.asc())
    ).all()
    return tuple(
        (
            row.id,
            row.revision,
            row.word_count,
            row.deleted_at,
            json.dumps(row.content, ensure_ascii=False, sort_keys=True),
        )
        for row in rows
    )


def _commit_keeping_manuscript(
    session: Session,
    novel_id: str,
    before: tuple[tuple[object, ...], ...],
) -> None:
    if _manuscript_snapshot(session, novel_id) != before:
        session.rollback()
        raise InvalidReference("创意候选不能修改正文。")
    _commit(session)


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise InvalidReference("这份内容没有写上。") from exc


def _require_novel(session: Session, novel_id: str) -> Novel:
    novel = catalog_repo.get_novel(session, novel_id)
    if novel is None:
        raise NotFound("作品不存在。")
    return novel


def _require_session(session: Session, session_id: str) -> IdeationSession:
    row = session.get(IdeationSession, session_id)
    if row is None or catalog_repo.get_novel(session, row.novel_id) is None:
        raise NotFound("这次引导不存在。")
    return row


def _require_candidate(session: Session, candidate_id: str) -> IdeationCandidate:
    row = session.get(IdeationCandidate, candidate_id)
    if row is None or catalog_repo.get_novel(session, row.novel_id) is None:
        raise NotFound("这份候选不存在。")
    return row


def _profile_from(payload: dict[str, object]) -> dict[str, object]:
    profile: dict[str, object] = {}
    for key in ("summary", "detail", "role", "desire", "fear", "note"):
        value = _as_text(payload.get(key))
        if value is not None:
            profile[key] = value
    return profile


def _string_list(value: object) -> list[str]:
    cleaned = _alias_list(value, strict=True)
    return cleaned or []


def _alias_list(value: object, *, strict: bool) -> list[str] | None:
    if value is None or value == "" or value == []:
        return []
    pieces: list[str] = []
    if isinstance(value, str):
        pieces = [part.strip() for part in value.replace("，", ",").split(",")]
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                pieces.append(item.strip())
            elif strict:
                raise InvalidReference("别名需要是文字。")
            else:
                return None
    elif strict:
        raise InvalidReference("别名需要是文字。")
    else:
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for alias in pieces:
        if alias == "" or alias.casefold() in seen:
            continue
        if len(alias) > 40:
            if strict:
                raise InvalidReference("别名过长。")
            continue
        if len(cleaned) == 20:
            if strict:
                raise InvalidReference("别名过多。")
            break
        seen.add(alias.casefold())
        cleaned.append(alias)
    return cleaned


def _text_field(value: object, limit: int, *, strict: bool) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None
    if len(cleaned) > limit:
        if strict:
            raise InvalidReference("有一段文字超过可保存的长度。请改短后再确认。")
        return cleaned[:limit]
    return cleaned


def _as_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _title(value: object, payload: dict[str, object]) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:200]
    for key in ("name", "title", "direction"):
        found = payload.get(key)
        if isinstance(found, str) and found.strip():
            return found.strip()[:200]
    return "候选"


def _object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("json")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("json")
    return {str(key): item for key, item in parsed.items()}


def _reject(strict: bool, message: str) -> dict[str, object] | None:
    if strict:
        raise InvalidReference(message)
    return None


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)
