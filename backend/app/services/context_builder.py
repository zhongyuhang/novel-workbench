"""Compile a novel-scoped context block for one writing task.

The compiler only prepares material. It does not change the manuscript,
formal memory, or outlines. Retrieval is exact name and alias match, a
bounded LIKE keyword search, and neighboring chapters. LIKE is not semantic
search. There is no vector index. Another novel is never loaded.

``token_estimate`` is a character count, not a tokenizer count.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.content import document_to_text
from app.core.errors import ContextCompileError
from app.core.redaction import redact_text
from app.models.catalog import Chapter, Novel, Volume
from app.models.memory import (
    ChapterSummary,
    EntityRelation,
    EntityState,
    StoryEntity,
    StoryEvent,
)
from app.models.planning import ChapterOutline, SceneCard, StoryArc, StoryPlan, VolumeOutline
from app.models.quality import Foreshadowing
from app.repositories import catalog as catalog_repo
from app.schemas.context import CompiledContext, ContextItem
from app.services.planning import planning_counts_as_fact

COMPILER_VERSION = "e7.v1"
EMPTY_MEMORY_WARNING = "尚未生成章节摘要。本次上下文只用了相邻章节和当前指令，长篇记忆还没写上。"
EARLIER_SUMMARY_WARNING = "已有章节摘要，但没有能纳入本次的现行前文摘要。本次仍主要依靠相邻章节。"
_ARC_LABELS = {
    "main": "主线",
    "subplot": "支线",
    "character": "人物线",
    "other": "其他",
}
DEFAULT_CONTEXT_BUDGET = 6000
ITEM_STORE_LIMIT = 4000
PROMPT_STORE_LIMIT = 100_000
SNAPSHOT_JSON_LIMIT = 180_000
_CJK_KEYWORD = re.compile(r"[\u4e00-\u9fff]{2,6}")
_SHRINK_LIMIT = 80
_SECRET_KEYS = {
    "api_key",
    "secret",
    "secret_ref",
    "authorization",
    "password",
    "access_token",
}


@dataclass(frozen=True)
class ContextPiece:
    key: str
    text: str
    required: bool
    shrinkable: bool
    rank: int


@dataclass
class _Candidate:
    id: str
    kind: str
    content: str
    source_type: str
    source_id: str | None
    source_revision: int | None
    certainty: str
    priority: int
    sequence: int
    hit_reason: str
    droppable: bool
    shrinkable: bool
    included: bool
    exclusion_reason: str | None
    warnings: list[str] = field(default_factory=list)
    conflict_text: str | None = None


def assemble_context(pieces: list[ContextPiece], budget: int) -> str:
    """Pack caller-marked pieces. Hard rules are not shrinkable in the compiler."""

    candidates = [
        _Candidate(
            id=piece.key,
            kind=piece.key,
            content=piece.text,
            source_type="piece",
            source_id=None,
            source_revision=None,
            certainty="confirmed" if piece.required else "inferred",
            priority=piece.rank,
            sequence=index,
            hit_reason="",
            droppable=not piece.required,
            shrinkable=piece.shrinkable,
            included=True,
            exclusion_reason=None,
        )
        for index, piece in enumerate(pieces)
    ]
    items, _warnings = _pack(candidates, budget=budget, pinned_include=[], pinned_exclude=[])
    return "\n\n".join(item.content for item in items if item.included and item.content.strip())


def render_included(compiled: CompiledContext) -> str:
    return "\n\n".join(
        item.content.strip() for item in compiled.items if item.included and item.content.strip()
    )


def compile_context(
    session: Session,
    *,
    novel_id: str,
    chapter_id: str | None,
    task_type: str,
    instruction: str,
    selection_text: str,
    chapter_text: str,
    target_revision: int | None,
    constraints: dict[str, object] | None,
    budget: int = DEFAULT_CONTEXT_BUDGET,
    pinned_include: list[str] | None = None,
    pinned_exclude: list[str] | None = None,
) -> CompiledContext:
    """Build a structured context. A missing novel is an error, not an empty prompt."""

    novel = catalog_repo.get_novel(session, novel_id)
    if novel is None:
        raise ContextCompileError("作品不存在，不能在没有作品范围时生成。")
    if novel.id != novel_id:
        raise ContextCompileError("作品范围不一致，已停止生成。")
    chapters = catalog_repo.list_chapters(session, novel.id)
    if chapter_id is not None and all(chapter.id != chapter_id for chapter in chapters):
        raise ContextCompileError("章节不存在，或不属于这本作品。已停止生成。")
    limit = budget if budget > 0 else 1
    candidates = _collect(
        session,
        novel=novel,
        chapters=chapters,
        chapter_id=chapter_id,
        task_type=task_type,
        instruction=instruction,
        selection_text=selection_text,
        chapter_text=chapter_text,
        constraints=constraints,
    )
    items, warnings = _pack(
        candidates,
        budget=limit,
        pinned_include=list(pinned_include or []),
        pinned_exclude=list(pinned_exclude or []),
    )
    warnings.extend(_constraint_conflicts(constraints))
    warnings.extend(_memory_gap_warnings(session, novel_id=novel.id, chapter_id=chapter_id))
    compiled = CompiledContext(
        task_type=task_type,
        novel_id=novel.id,
        chapter_id=chapter_id,
        target_revision=target_revision,
        items=items,
        total_token_estimate=_included_length(items),
        budget=limit,
        warnings=warnings,
        compiler_version=COMPILER_VERSION,
        context_hash="",
    )
    compiled.context_hash = _context_hash(compiled)
    return compiled


def build_memory_context(
    session: Session,
    *,
    novel_id: str,
    chapter_id: str | None,
    instruction: str,
    selection_text: str,
    chapter_text: str,
    budget: int = DEFAULT_CONTEXT_BUDGET,
) -> str:
    compiled = compile_context(
        session,
        novel_id=novel_id,
        chapter_id=chapter_id,
        task_type="continue",
        instruction=instruction,
        selection_text=selection_text,
        chapter_text=chapter_text,
        target_revision=None,
        constraints=None,
        budget=budget,
    )
    return render_included(compiled)


def present_context(
    compiled: CompiledContext, *, content_limit: int = ITEM_STORE_LIMIT
) -> CompiledContext:
    """Copy a compile result with stored bodies capped. Estimates stay on the full text."""

    items: list[ContextItem] = []
    warnings = list(compiled.warnings)
    capped = False
    for item in compiled.items:
        content = item.content
        item_warnings = list(item.warnings)
        if len(content) > content_limit:
            capped = True
            content = content[:content_limit].rstrip() + "…（副本已按上限缩短）"
            item_warnings.append(
                "这条材料的存档副本已缩短。字符估算仍按全文。硬规则送给模型的仍是全文。"
            )
        items.append(item.model_copy(update={"content": content, "warnings": item_warnings}))
    if capped and not any("存档副本" in warning for warning in warnings):
        warnings.append("部分材料的存档副本已按上限缩短。生成使用的是编译时的全文。")
    return compiled.model_copy(update={"items": items, "warnings": warnings})


def snapshot_context_fields(compiled: CompiledContext, prompt: str) -> dict[str, object]:
    """Fields merged into ``ai_tasks.input_snapshot``. Secrets are not copied here."""

    presented = present_context(compiled)
    items = [item.model_dump() for item in presented.items]
    return {
        "compiler_version": presented.compiler_version,
        "context_budget": presented.budget,
        "context_warnings": list(presented.warnings),
        "context_hash": presented.context_hash,
        "context_total_token_estimate": presented.total_token_estimate,
        "context_legacy": False,
        "context_items": items,
        "prompt": prompt,
    }


def context_from_snapshot(
    *,
    task_type: str,
    novel_id: str,
    chapter_id: str | None,
    snapshot: dict[str, object],
) -> CompiledContext:
    version = snapshot.get("compiler_version")
    raw_items = snapshot.get("context_items")
    if not isinstance(version, str) or version == "" or not isinstance(raw_items, list):
        return _legacy_context(task_type, novel_id, chapter_id, snapshot)
    items: list[ContextItem] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            return _legacy_context(task_type, novel_id, chapter_id, snapshot)
        try:
            items.append(ContextItem.model_validate(entry))
        except ValueError:
            return _legacy_context(task_type, novel_id, chapter_id, snapshot)
    warnings_raw = snapshot.get("context_warnings")
    warnings = (
        [item for item in warnings_raw if isinstance(item, str)]
        if isinstance(warnings_raw, list)
        else []
    )
    budget = snapshot.get("context_budget")
    total = snapshot.get("context_total_token_estimate")
    target = snapshot.get("target_revision")
    digest = snapshot.get("context_hash")
    return CompiledContext(
        task_type=task_type,
        novel_id=novel_id,
        chapter_id=chapter_id,
        target_revision=target if isinstance(target, int) else None,
        items=items,
        total_token_estimate=total if isinstance(total, int) else 0,
        budget=budget if isinstance(budget, int) else 0,
        warnings=warnings,
        compiler_version=version,
        context_hash=digest if isinstance(digest, str) else "",
        legacy=False,
    )


def redact_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    redacted = _redact_value(snapshot)
    if isinstance(redacted, dict):
        return {str(key): value for key, value in redacted.items()}
    return {}


def fit_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    """Keep the stored task snapshot under the size cap. This does not alter generation."""

    current = redact_snapshot(snapshot)
    prompt = current.get("prompt")
    if isinstance(prompt, str) and len(prompt) > PROMPT_STORE_LIMIT:
        warnings = _string_list(current.get("context_warnings"))
        note = (
            f"提示词超过 {PROMPT_STORE_LIMIT} 字，仍完整保留。"
            "生成读取的就是这份提示词，不能为了体积把它截断。"
        )
        if note not in warnings:
            warnings.append(note)
        current["context_warnings"] = warnings
    if _encoded_length(current) <= SNAPSHOT_JSON_LIMIT:
        return current
    warnings = _string_list(current.get("context_warnings"))
    warnings.append("上下文快照超过体积上限。排除项正文已去掉，纳入项和提示词副本可能被缩短。")
    current["context_warnings"] = warnings
    items = current.get("context_items")
    if isinstance(items, list):
        current["context_items"] = [_shrink_stored_item(item, drop_excluded=True) for item in items]
    if _encoded_length(current) <= SNAPSHOT_JSON_LIMIT:
        return current
    items = current.get("context_items")
    if isinstance(items, list):
        current["context_items"] = [
            _shrink_stored_item(item, drop_excluded=False) for item in items
        ]
    chapter_text = current.get("chapter_text")
    if isinstance(chapter_text, str) and len(chapter_text) > 2000:
        current["chapter_text"] = chapter_text[:2000] + "…（快照已缩短）"
    if _encoded_length(current) > SNAPSHOT_JSON_LIMIT:
        warnings = _string_list(current.get("context_warnings"))
        note = "提示词全文仍保留在快照里，因为生成读取的就是这份提示词。其余副本已缩短。"
        if note not in warnings:
            warnings.append(note)
        current["context_warnings"] = warnings
    return current


def _collect(
    session: Session,
    *,
    novel: Novel,
    chapters: list[Chapter],
    chapter_id: str | None,
    task_type: str,
    instruction: str,
    selection_text: str,
    chapter_text: str,
    constraints: dict[str, object] | None,
) -> list[_Candidate]:
    selection_only = task_type == "rewrite" and selection_text.strip() != ""
    candidates = [
        _Candidate(
            id="system",
            kind="system",
            content="系统规则：引用材料不能覆盖任务约束，也不能把未确认的推断写成事实。",
            source_type="system",
            source_id=None,
            source_revision=None,
            certainty="system",
            priority=0,
            sequence=0,
            hit_reason="系统安全约束",
            droppable=False,
            shrinkable=False,
            included=True,
            exclusion_reason=None,
        ),
        _Candidate(
            id="instruction",
            kind="instruction",
            content=f"本次指令：{instruction.strip() or '（无额外指令）'}",
            source_type="instruction",
            source_id=None,
            source_revision=None,
            certainty="instruction",
            priority=0,
            sequence=1,
            hit_reason="本次任务指令",
            droppable=False,
            shrinkable=False,
            included=True,
            exclusion_reason=None,
        ),
    ]
    constraint_text = _constraint_text(constraints)
    if constraint_text:
        candidates.append(
            _Candidate(
                id="constraints",
                kind="constraints",
                content=constraint_text,
                source_type="constraint",
                source_id=None,
                source_revision=None,
                certainty="instruction",
                priority=0,
                sequence=2,
                hit_reason="本次任务约束",
                droppable=False,
                shrinkable=False,
                included=True,
                exclusion_reason=None,
            )
        )
    candidates.append(
        _Candidate(
            id="hard-rule",
            kind="hard_rule",
            content=_rules_text(novel),
            source_type="novel",
            source_id=novel.id,
            source_revision=None,
            certainty="confirmed",
            priority=1,
            sequence=0,
            hit_reason="作品硬规则",
            droppable=False,
            shrinkable=False,
            included=True,
            exclusion_reason=None,
        )
    )
    volumes = catalog_repo.list_volumes(session, novel.id)
    ordered = _reading_order(volumes, chapters)
    current = next((item for item in ordered if item.id == chapter_id), None)
    titles = {chapter.id: chapter for chapter in chapters}
    previous: Chapter | None = None
    following: Chapter | None = None
    if current is not None and current.novel_id == novel.id:
        candidates.append(
            _Candidate(
                id="chapter",
                kind="chapter",
                content=(
                    f"当前章节约束：{current.title}"
                    f"（修订 {current.revision}，状态 {current.status}）"
                ),
                source_type="chapter",
                source_id=current.id,
                source_revision=current.revision,
                certainty="confirmed",
                priority=1,
                sequence=1,
                hit_reason="当前章节",
                droppable=False,
                shrinkable=False,
                included=True,
                exclusion_reason=None,
            )
        )
        previous = _neighbor(ordered, current.id, -1)
        following = _neighbor(ordered, current.id, 1)
        if previous is not None and previous.novel_id == novel.id:
            tail = _tail(document_to_text(previous.content))
            candidates.append(
                _Candidate(
                    id=f"previous:{previous.id}",
                    kind="previous_chapter",
                    content=f"前文衔接：{previous.title}\n{tail or '（上一章没有正文）'}",
                    source_type="chapter",
                    source_id=previous.id,
                    source_revision=previous.revision,
                    certainty="confirmed",
                    priority=4,
                    sequence=0,
                    hit_reason="相邻上一章",
                    droppable=False,
                    shrinkable=True,
                    included=True,
                    exclusion_reason=None,
                )
            )
        if following is not None and following.novel_id == novel.id:
            opening = document_to_text(following.content).strip()[:180]
            if opening:
                candidates.append(
                    _Candidate(
                        id=f"next:{following.id}",
                        kind="next_chapter",
                        content=f"相邻章节开头：{following.title}\n{opening}",
                        source_type="chapter",
                        source_id=following.id,
                        source_revision=following.revision,
                        certainty="confirmed",
                        priority=20,
                        sequence=0,
                        hit_reason="相邻下一章",
                        droppable=not selection_only,
                        shrinkable=False,
                        included=not selection_only,
                        exclusion_reason="选区改写默认不纳入相邻后章开头"
                        if selection_only
                        else None,
                    )
                )
    candidates.extend(_plan_candidates(session, novel.id, current))
    haystack = "\n".join(
        [selection_text, instruction]
        if selection_only
        else [chapter_text, instruction, selection_text]
    )
    entities = _entities(session, novel.id)
    states = _latest_states(session, [entity.id for entity in entities])
    matched_names: list[str] = []
    matched_ids: set[str] = set()
    for entity in entities:
        if entity.novel_id != novel.id:
            continue
        matched = _name_hit(entity, haystack)
        if matched is None:
            continue
        matched_names.extend(_names(entity))
        matched_ids.add(entity.id)
        candidates.append(_entity_candidate(entity, states.get(entity.id), titles, matched=matched))
    entity_names = {entity.id: entity.name for entity in entities if entity.novel_id == novel.id}
    for relation in _relations_for_entities(session, novel.id, matched_ids):
        candidates.append(_relation_candidate(relation, entity_names, titles))
    event_text = "" if selection_only else chapter_text
    for event in _related_events(session, novel.id, instruction, selection_text, event_text):
        if event.novel_id != novel.id:
            continue
        candidates.append(_event_candidate(event, titles))
    neighbor_ids = {chapter.id for chapter in (current, previous, following) if chapter is not None}
    for summary, chapter in _summaries(session, novel.id):
        if chapter.novel_id != novel.id:
            continue
        candidates.extend(
            _summary_candidates(
                summary,
                chapter,
                current=current,
                ordered=ordered,
                neighbor_ids=neighbor_ids,
                selection_only=selection_only,
            )
        )
    if current is not None:
        candidates.extend(
            _foreshadowing_candidates(
                session,
                novel_id=novel.id,
                current=current,
                neighbor_ids=neighbor_ids,
                instruction=instruction,
                selection_text=selection_text,
                names=matched_names,
            )
        )
    return candidates


def _plan_candidates(
    session: Session,
    novel_id: str,
    current: Chapter | None,
) -> list[_Candidate]:
    rows: list[_Candidate] = []
    plan = session.scalar(select(StoryPlan).where(StoryPlan.novel_id == novel_id))
    if plan is not None and plan.novel_id == novel_id:
        rows.append(_story_plan_candidate(plan))
    arcs = session.scalars(
        select(StoryArc)
        .where(StoryArc.novel_id == novel_id)
        .order_by(StoryArc.sort_order.asc(), StoryArc.id.asc())
    )
    for arc in arcs:
        if arc.novel_id != novel_id:
            continue
        rows.append(_arc_candidate(arc))
    if current is not None and current.novel_id == novel_id and current.volume_id is not None:
        volume = session.get(Volume, current.volume_id)
        if volume is not None and volume.novel_id == novel_id:
            volume_outline = session.scalar(
                select(VolumeOutline).where(
                    VolumeOutline.volume_id == volume.id,
                    VolumeOutline.novel_id == novel_id,
                )
            )
            if (
                volume_outline is not None
                and volume_outline.novel_id == novel_id
                and volume_outline.volume_id == volume.id
            ):
                rows.append(_volume_outline_candidate(volume_outline))
    if current is None:
        return rows
    outline = session.scalar(
        select(ChapterOutline).where(
            ChapterOutline.chapter_id == current.id,
            ChapterOutline.novel_id == novel_id,
        )
    )
    if outline is not None and outline.novel_id == novel_id and outline.chapter_id == current.id:
        rows.append(_outline_candidate(outline))
    scenes = session.scalars(
        select(SceneCard)
        .where(SceneCard.chapter_id == current.id, SceneCard.novel_id == novel_id)
        .order_by(SceneCard.sort_order.asc(), SceneCard.id.asc())
    )
    names = _entity_names(session, novel_id)
    for scene in scenes:
        if scene.novel_id != novel_id or scene.chapter_id != current.id:
            continue
        rows.append(_scene_candidate(scene, names))
    return rows


def _story_plan_candidate(plan: StoryPlan) -> _Candidate:
    fact = planning_counts_as_fact(plan.status)
    lines = ["已确认作品大纲：" if fact else "未确认作品大纲（不是事实）："]
    if plan.logline and plan.logline.strip():
        lines.append(f"一句话：{plan.logline.strip()}")
    if plan.body and plan.body.strip():
        lines.append(plan.body.strip())
    if plan.ending_intent and plan.ending_intent.strip():
        lines.append(f"结局意向：{plan.ending_intent.strip()}")
    if len(lines) == 1:
        lines.append("（没有写下大纲正文）")
    return _Candidate(
        id=f"plan:{plan.id}",
        kind="story_plan",
        content="\n".join(lines),
        source_type="story_plan",
        source_id=plan.id,
        source_revision=plan.revision,
        certainty="confirmed" if fact else plan.status,
        priority=2,
        sequence=0,
        hit_reason="已确认作品大纲" if fact else "作品大纲未确认",
        droppable=not fact,
        shrinkable=False,
        included=fact,
        exclusion_reason=None if fact else _plan_exclusion(plan.status),
    )


def _arc_candidate(arc: StoryArc) -> _Candidate:
    fact = planning_counts_as_fact(arc.status)
    label = _ARC_LABELS.get(arc.arc_type, "其他")
    lines = [
        f"已确认故事线（{label}）：{arc.title}"
        if fact
        else f"未确认故事线（不是事实，{label}）：{arc.title}"
    ]
    if arc.summary and arc.summary.strip():
        lines.append(arc.summary.strip())
    else:
        lines.append("（没有写下故事线摘要）")
    return _Candidate(
        id=f"arc:{arc.id}",
        kind="story_arc",
        content="\n".join(lines),
        source_type="story_arc",
        source_id=arc.id,
        source_revision=arc.revision,
        certainty="confirmed" if fact else arc.status,
        priority=2,
        sequence=2 + arc.sort_order,
        hit_reason="已确认故事线" if fact else "故事线未确认",
        droppable=not fact,
        shrinkable=False,
        included=fact,
        exclusion_reason=None if fact else _plan_exclusion(arc.status),
    )


def _volume_outline_candidate(outline: VolumeOutline) -> _Candidate:
    fact = planning_counts_as_fact(outline.status)
    lines = ["已确认卷大纲：" if fact else "未确认卷大纲（不是事实）："]
    _add_line(lines, "目标", outline.goal)
    _add_line(lines, "关键事件", outline.key_events)
    _add_line(lines, "起始状态", outline.start_state)
    _add_line(lines, "结束状态", outline.end_state)
    if len(lines) == 1:
        lines.append("（没有写下卷目标）")
    return _Candidate(
        id=f"volume-outline:{outline.id}",
        kind="volume_outline",
        content="\n".join(lines),
        source_type="volume_outline",
        source_id=outline.id,
        source_revision=outline.revision,
        certainty="confirmed" if fact else outline.status,
        priority=2,
        sequence=1,
        hit_reason="已确认卷大纲" if fact else "卷大纲未确认",
        droppable=not fact,
        shrinkable=False,
        included=fact,
        exclusion_reason=None if fact else _plan_exclusion(outline.status),
    )


def _outline_candidate(outline: ChapterOutline) -> _Candidate:
    fact = planning_counts_as_fact(outline.status)
    lines = ["已确认章节大纲：" if fact else "未确认章节大纲（不是事实）："]
    _add_line(lines, "目标", outline.goal)
    _add_line(lines, "必须推进", outline.must_advance)
    _add_line(lines, "必须出现", outline.required_events)
    _add_line(lines, "允许揭露", outline.allowed_reveals)
    _add_line(lines, "禁止揭露", outline.forbidden_reveals)
    if outline.target_words is not None:
        lines.append(f"目标字数：{outline.target_words}")
    _add_line(lines, "结尾", outline.ending_hook)
    if len(lines) == 1:
        lines.append("（没有写下章节目标）")
    forbidden = outline.forbidden_reveals.strip() if outline.forbidden_reveals else ""
    return _Candidate(
        id=f"outline:{outline.id}",
        kind="chapter_outline",
        content="\n".join(lines),
        source_type="chapter_outline",
        source_id=outline.id,
        source_revision=outline.revision,
        certainty="confirmed" if fact else outline.status,
        priority=2,
        sequence=1,
        hit_reason="已确认章节大纲" if fact else "章节大纲未确认",
        droppable=not fact,
        shrinkable=False,
        included=fact,
        exclusion_reason=None if fact else _plan_exclusion(outline.status),
        conflict_text=forbidden if fact and len(forbidden) >= 4 else None,
    )


def _scene_candidate(scene: SceneCard, names: dict[str, str]) -> _Candidate:
    fact = planning_counts_as_fact(scene.status)
    lines = [
        f"已确认场景卡片（顺序 {scene.sort_order}）：" if fact else "未确认场景卡片（不是事实）："
    ]
    _add_line(lines, "目标", scene.goal)
    if scene.location_entity_id:
        place_name = names.get(scene.location_entity_id, "未解析的地点")
        lines.append(f"地点：{place_name}（实体 {scene.location_entity_id}）")
    characters = [
        names.get(item, "未解析的人物")
        for item in scene.character_entity_ids
        if isinstance(item, str)
    ]
    if characters:
        lines.append("出场人物：" + "、".join(characters))
    _add_line(lines, "冲突", scene.conflict)
    _add_line(lines, "转折", scene.turning_point)
    _add_line(lines, "预期结果", scene.expected_outcome)
    _add_line(lines, "必须传达", scene.must_convey)
    _add_line(lines, "不得透露", scene.must_not_reveal)
    hidden = scene.must_not_reveal.strip() if scene.must_not_reveal else ""
    return _Candidate(
        id=f"scene:{scene.id}",
        kind="scene_card",
        content="\n".join(lines),
        source_type="scene_card",
        source_id=scene.id,
        source_revision=scene.revision,
        certainty="confirmed" if fact else scene.status,
        priority=3,
        sequence=scene.sort_order,
        hit_reason="已确认场景卡片" if fact else "场景卡片未确认",
        droppable=not fact,
        shrinkable=False,
        included=fact,
        exclusion_reason=None if fact else _plan_exclusion(scene.status),
        conflict_text=hidden if fact and len(hidden) >= 4 else None,
    )


def _entity_candidate(
    entity: StoryEntity,
    state: EntityState | None,
    titles: dict[str, Chapter],
    *,
    matched: str,
) -> _Candidate:
    certain = entity.status != "unknown"
    label = _entity_label(entity.entity_type)
    lines = [
        f"{'已确认设定' if certain else '不确定推断（不是已确认事实）'}：{label}「{entity.name}」"
    ]
    aliases = _strings(entity.aliases)
    if aliases:
        lines.append("别名：" + "、".join(aliases))
    profile = entity.profile if isinstance(entity.profile, dict) else {}
    summary = profile.get("summary")
    if isinstance(summary, str) and summary.strip():
        lines.append(summary.strip())
    warnings: list[str] = []
    source_revision: int | None = None
    if state is not None:
        chapter = titles.get(state.chapter_id)
        title = chapter.title if chapter is not None else "未知章节"
        source_revision = state.source_revision
        revision = source_revision if source_revision is not None else "未知"
        lines.append(f"人物当前状态：来源章节「{title}」修订 {revision}")
        validity = _validity_text(state.valid_from_text, state.valid_until_text)
        if validity:
            lines.append(validity)
        if state.evidence_quote:
            lines.append(f"证据：{state.evidence_quote}")
        if chapter is None:
            warnings.append("状态的来源章节不在这本作品的可见章节里。")
        elif source_revision is not None and source_revision != chapter.revision:
            warnings.append(
                f"状态来源修订 {source_revision} 落后于章节「{chapter.title}」"
                f"当前修订 {chapter.revision}。"
            )
    hit = "实体别名命中" if matched == "alias" else "实体名称命中"
    if not certain:
        hit = f"{hit}，但是不确定推断"
    return _Candidate(
        id=f"entity:{entity.id}",
        kind="entity",
        content="\n".join(lines),
        source_type="entity",
        source_id=entity.id,
        source_revision=source_revision,
        certainty="confirmed" if certain else "uncertain",
        priority=10 if certain else 70,
        sequence=0,
        hit_reason=hit,
        droppable=not certain,
        shrinkable=certain,
        included=True,
        exclusion_reason=None,
        warnings=warnings,
    )


def _validity_text(start: str | None, end: str | None) -> str | None:
    start_text = start.strip() if isinstance(start, str) else ""
    end_text = end.strip() if isinstance(end, str) else ""
    if start_text and end_text:
        return f"有效时间：{start_text} 至 {end_text}"
    if start_text:
        return f"有效时间：自 {start_text} 起"
    if end_text:
        return f"有效时间：至 {end_text} 止"
    return None


def _relations_for_entities(
    session: Session,
    novel_id: str,
    entity_ids: set[str],
) -> list[EntityRelation]:
    if not entity_ids:
        return []
    rows = session.scalars(
        select(EntityRelation)
        .where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.deleted_at.is_(None),
        )
        .order_by(EntityRelation.created_at.asc(), EntityRelation.id.asc())
    ).all()
    return [
        row
        for row in rows
        if row.novel_id == novel_id
        and (row.from_entity_id in entity_ids or row.to_entity_id in entity_ids)
    ]


def _relation_candidate(
    relation: EntityRelation,
    names: dict[str, str],
    titles: dict[str, Chapter],
) -> _Candidate:
    left = names.get(relation.from_entity_id, "未解析的设定")
    right = names.get(relation.to_entity_id, "未解析的设定")
    ended = relation.status == "ended"
    uncertain = relation.status == "unknown"
    heading = "不确定关系（不是已确认事实）" if uncertain else "已确认关系"
    if ended:
        heading = "已结束的关系"
    lines = [f"{heading}：{left} —{relation.relation_type}→ {right}"]
    if relation.storyline:
        lines.append(f"故事线标签：{relation.storyline}")
    if relation.story_time_text:
        lines.append(f"故事时间：{relation.story_time_text}")
    else:
        lines.append("故事时间未填写")
    chapter = titles.get(relation.source_chapter_id) if relation.source_chapter_id else None
    warnings: list[str] = []
    if relation.source_chapter_id:
        title = chapter.title if chapter is not None else "未知章节"
        revision = relation.source_revision if relation.source_revision is not None else "未知"
        lines.append(f"来源章节「{title}」修订 {revision}")
        if chapter is None:
            warnings.append("关系的来源章节不在这本作品的可见章节里。")
        elif relation.source_revision is not None and relation.source_revision != chapter.revision:
            warnings.append(
                f"关系来源修订 {relation.source_revision} 落后于章节「{chapter.title}」"
                f"当前修订 {chapter.revision}。"
            )
    if relation.evidence_quote:
        lines.append(f"证据：{relation.evidence_quote}")
    else:
        lines.append("证据未填写")
    return _Candidate(
        id=f"relation:{relation.id}",
        kind="entity_relation",
        content="\n".join(lines),
        source_type="entity_relation",
        source_id=relation.id,
        source_revision=relation.source_revision,
        certainty="uncertain" if uncertain else "confirmed",
        priority=15 if not uncertain else 70,
        sequence=0,
        hit_reason="人物关系，关联到已命中的设定",
        droppable=True,
        shrinkable=False,
        included=True,
        exclusion_reason=None,
        warnings=warnings,
    )


def _event_candidate(event: StoryEvent, titles: dict[str, Chapter]) -> _Candidate:
    certain = event.certainty == "confirmed"
    heading = "已确认事件" if certain else "不确定推断（不是已确认事实）"
    revision = event.source_revision if event.source_revision is not None else "未知"
    warnings: list[str] = []
    if event.chapter_id is None:
        title = "尚未关联章节"
    else:
        chapter = titles.get(event.chapter_id)
        title = chapter.title if chapter is not None else "未知章节"
        if chapter is None:
            warnings.append("事件的来源章节不在这本作品的可见章节里。")
        elif event.source_revision is not None and event.source_revision != chapter.revision:
            warnings.append(
                f"事件来源修订 {event.source_revision} 落后于章节「{chapter.title}」"
                f"当前修订 {chapter.revision}。"
            )
    when = (event.event_time_text or "").strip()
    time_line = f"故事时间：{when}" if when else "故事时间未填写"
    label = (event.title or "").strip()
    body = f"{label}。{event.description.strip()}" if label else event.description.strip()
    text = (
        f"{heading}：{body}\n"
        f"{time_line}\n"
        f"来源章节「{title}」修订 {revision}\n"
        f"证据：{event.evidence_quote}"
    )
    return _Candidate(
        id=f"event:{event.id}",
        kind="event",
        content=text,
        source_type="story_event",
        source_id=event.id,
        source_revision=event.source_revision,
        certainty=event.certainty,
        priority=30 if certain else 70,
        sequence=0,
        hit_reason="事件关键词命中（普通匹配，不是语义检索）",
        droppable=True,
        shrinkable=False,
        included=True,
        exclusion_reason=None,
        warnings=warnings,
    )


def _summary_candidates(
    summary: ChapterSummary,
    chapter: Chapter,
    *,
    current: Chapter | None,
    ordered: list[Chapter],
    neighbor_ids: set[str],
    selection_only: bool,
) -> list[_Candidate]:
    if current is not None and chapter.id == current.id and summary.status == "current":
        return []
    distance = _distance(ordered, current.id if current is not None else None, chapter.id)
    stale = summary.status != "current" or summary.source_revision != chapter.revision
    if summary.status == "current" and not stale:
        if selection_only:
            return [
                _Candidate(
                    id=f"summary:{summary.id}",
                    kind="summary",
                    content=(
                        f"较远章节摘要：{chapter.title}（来源修订 {summary.source_revision}）\n"
                        f"{summary.summary.strip()}"
                    ),
                    source_type="chapter_summary",
                    source_id=summary.id,
                    source_revision=summary.source_revision,
                    certainty="inferred",
                    priority=60 + min(distance, 20),
                    sequence=distance,
                    hit_reason="较远章节的现行摘要",
                    droppable=True,
                    shrinkable=False,
                    included=False,
                    exclusion_reason="选区改写默认不纳入较远章节摘要",
                )
            ]
        return [
            _Candidate(
                id=f"summary:{summary.id}",
                kind="summary",
                content=(
                    f"较远章节摘要：{chapter.title}（来源修订 {summary.source_revision}）\n"
                    f"{summary.summary.strip()}"
                ),
                source_type="chapter_summary",
                source_id=summary.id,
                source_revision=summary.source_revision,
                certainty="inferred",
                priority=60 + min(distance, 20),
                sequence=distance,
                hit_reason="较远章节的现行摘要",
                droppable=True,
                shrinkable=False,
                included=True,
                exclusion_reason=None,
            )
        ]
    if chapter.id not in neighbor_ids and (current is None or chapter.id != current.id):
        return []
    reason = "摘要已过期，未当作事实"
    if summary.status == "current" and summary.source_revision != chapter.revision:
        reason = "摘要来源修订与章节正文不一致，未当作事实"
    return [
        _Candidate(
            id=f"summary:{summary.id}",
            kind="summary",
            content=(
                f"过期摘要：{chapter.title}（来源修订 {summary.source_revision}，"
                f"章节修订 {chapter.revision}）\n{summary.summary.strip()}"
            ),
            source_type="chapter_summary",
            source_id=summary.id,
            source_revision=summary.source_revision,
            certainty="uncertain",
            priority=80,
            sequence=distance,
            hit_reason="相邻或当前章节的过期摘要",
            droppable=True,
            shrinkable=False,
            included=False,
            exclusion_reason=reason,
            warnings=["摘要来源修订已落后于正文，或摘要已被标为过期。"],
        )
    ]


def _foreshadowing_candidates(
    session: Session,
    *,
    novel_id: str,
    current: Chapter,
    neighbor_ids: set[str],
    instruction: str,
    selection_text: str,
    names: list[str],
) -> list[_Candidate]:
    rows = list(
        session.scalars(
            select(Foreshadowing)
            .where(Foreshadowing.novel_id == novel_id)
            .order_by(Foreshadowing.created_at.asc(), Foreshadowing.id.asc())
        )
    )
    keys = _keywords(f"{instruction}\n{selection_text}")
    found: list[_Candidate] = []
    for row in rows:
        if row.novel_id != novel_id:
            continue
        linked = row.introduced_chapter_id in neighbor_ids or row.payoff_chapter_id in neighbor_ids
        blob = f"{row.description}\n{row.evidence_quote or ''}"
        named = any(name in blob for name in names if len(name) >= 2)
        keyed = any(key in blob for key in keys)
        if not linked and not named and not keyed:
            continue
        reason = "伏笔关联当前或相邻章节"
        if not linked and named:
            reason = "伏笔文本命中已匹配的实体名"
        elif not linked and keyed:
            reason = "伏笔文本命中指令中的词语（普通匹配，不是语义检索）"
        abandoned = row.status == "abandoned"
        quote = row.evidence_quote.strip() if row.evidence_quote else ""
        content = f"伏笔（{row.status}）：{row.description.strip()}"
        if quote:
            content = f"{content}\n证据：{quote}"
        times = [
            ("事件实际发生", row.event_time_text),
            ("角色发现", row.character_discovered_text),
            ("向读者揭示", row.reader_revealed_text),
        ]
        details = [f"{label}：{value.strip()}" for label, value in times if value and value.strip()]
        if details:
            content = f"{content}\n" + "；".join(details)
        found.append(
            _Candidate(
                id=f"foreshadow:{row.id}",
                kind="foreshadowing",
                content=content,
                source_type="foreshadowing",
                source_id=row.id,
                source_revision=None,
                certainty="confirmed"
                if row.status in {"open", "planned", "resolved"}
                else "uncertain",
                priority=40,
                sequence=len(found),
                hit_reason=reason,
                droppable=True,
                shrinkable=False,
                included=not abandoned,
                exclusion_reason="伏笔已放弃" if abandoned else None,
            )
        )
        if len(found) >= 8:
            break
    return found


def _pack(
    candidates: list[_Candidate],
    *,
    budget: int,
    pinned_include: list[str],
    pinned_exclude: list[str],
) -> tuple[list[ContextItem], list[str]]:
    warnings: list[str] = []
    known = {item.id for item in candidates}
    for pinned in pinned_include:
        if pinned not in known:
            warnings.append(
                f"固定纳入「{pinned}」不存在或不属于这本作品，已忽略，没有读取其他作品。"
            )
    both = sorted(set(pinned_include).intersection(pinned_exclude))
    if both:
        warnings.append("同一材料同时被固定纳入和排除，本次按排除处理。")
    if "system" in pinned_exclude:
        warnings.append("系统安全约束不能从本次上下文排除。")

    include_ids = set(pinned_include)
    exclude_ids = set(pinned_exclude)
    for candidate in candidates:
        if candidate.id in exclude_ids and candidate.kind != "system":
            candidate.included = False
            candidate.exclusion_reason = "用户本次排除"
            if candidate.kind == "hard_rule":
                warnings.append("你排除了作品硬规则。本次生成不会使用它，正式设定没有被修改。")
            continue
        if candidate.id in include_ids:
            candidate.included = True
            candidate.exclusion_reason = None
            candidate.droppable = False
            if candidate.certainty not in {"confirmed", "system", "instruction"}:
                candidate.warnings.append(
                    "这是未确认材料，只因本次固定纳入而出现，不是已确认事实。"
                )
            if candidate.hit_reason and "用户固定纳入" not in candidate.hit_reason:
                candidate.hit_reason = f"{candidate.hit_reason}；用户固定纳入"

    included = [item for item in candidates if item.included]
    while included and _candidate_length(included) > budget:
        droppable = [item for item in included if item.droppable and item.id not in include_ids]
        if not droppable:
            break
        victim = max(droppable, key=lambda item: (item.priority, item.sequence, item.id))
        victim.included = False
        victim.exclusion_reason = "超出上下文预算"
        included = [item for item in candidates if item.included]

    while included and _candidate_length(included) > budget:
        shrinkable = [
            item for item in included if item.shrinkable and item.content != _shrunk(item.content)
        ]
        if not shrinkable:
            break
        victim = max(shrinkable, key=lambda item: (len(item.content), item.id))
        victim.content = _shrunk(victim.content)
        victim.warnings.append("这段引用已按预算截短。硬规则和已确认大纲没有被截断。")

    over_budget = bool(included) and _candidate_length(included) > budget
    if over_budget:
        warnings.append(
            "上下文预算不够放下硬规则、已确认大纲或你固定纳入的材料。"
            "这些内容已完整保留，没有静默截断。可以调高预算或调整本次选择。"
        )
    if over_budget and any(item.id in include_ids and item.included for item in candidates):
        warnings.append("用户固定纳入的材料超出预算，已保留。请调整本次选择或提高预算。")

    for candidate in candidates:
        if (
            candidate.included
            and candidate.conflict_text
            and candidate.conflict_text in _instruction_blob(candidates)
        ):
            note = (
                "本次指令或约束与已确认大纲里的禁止揭露信息重叠。编译器没有用其中一方覆盖另一方。"
            )
            if note not in candidate.warnings:
                candidate.warnings.append(note)
            if note not in warnings:
                warnings.append(note)
        for note in candidate.warnings:
            if note not in warnings:
                warnings.append(note)

    ordered = sorted(candidates, key=lambda item: (item.priority, item.sequence, item.id))
    return [_to_item(item) for item in ordered], warnings


def _to_item(candidate: _Candidate) -> ContextItem:
    return ContextItem(
        id=candidate.id,
        kind=candidate.kind,
        content=candidate.content,
        source_type=candidate.source_type,
        source_id=candidate.source_id,
        source_revision=candidate.source_revision,
        certainty=candidate.certainty,
        priority=candidate.priority,
        token_estimate=len(candidate.content),
        included=candidate.included,
        exclusion_reason=candidate.exclusion_reason,
        hit_reason=candidate.hit_reason,
        warnings=list(candidate.warnings),
    )


def _instruction_blob(candidates: list[_Candidate]) -> str:
    parts = [item.content for item in candidates if item.kind in {"instruction", "constraints"}]
    return "\n".join(parts)


def _constraint_conflicts(constraints: dict[str, object] | None) -> list[str]:
    if not constraints:
        return []
    must_include = constraints.get("must_include")
    must_avoid = constraints.get("must_avoid")
    if (
        isinstance(must_include, str)
        and isinstance(must_avoid, str)
        and must_include.strip()
        and must_include.strip() == must_avoid.strip()
    ):
        return ["本次约束里「必须包含」和「不要出现」写了同一句话，请作者判断。"]
    return []


def _constraint_text(constraints: dict[str, object] | None) -> str:
    if not constraints:
        return ""
    lines: list[str] = ["本次任务约束："]
    max_words = constraints.get("max_words")
    if isinstance(max_words, int):
        lines.append(f"篇幅大约不超过 {max_words} 字。")
    viewpoint = constraints.get("viewpoint")
    if isinstance(viewpoint, str) and viewpoint.strip():
        lines.append(f"视角：{viewpoint.strip()}")
    tone = constraints.get("tone")
    if isinstance(tone, str) and tone.strip():
        lines.append(f"语气：{tone.strip()}")
    must_include = constraints.get("must_include")
    if isinstance(must_include, str) and must_include.strip():
        lines.append(f"必须包含：{must_include.strip()}")
    must_avoid = constraints.get("must_avoid")
    if isinstance(must_avoid, str) and must_avoid.strip():
        lines.append(f"不要出现：{must_avoid.strip()}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _plan_exclusion(status: str) -> str:
    if status == "draft":
        return "草稿不能当作事实"
    if status == "stale":
        return "大纲已过期，需要复核后才能当作事实"
    if status == "archived":
        return "已归档，未纳入"
    return "未确认，不能当作事实"


def _rules_text(novel: Novel) -> str:
    lines = ["作品硬规则："]
    if novel.genre and novel.genre.strip():
        lines.append(f"题材：{novel.genre.strip()}")
    if novel.core_conflict and novel.core_conflict.strip():
        lines.append(f"核心冲突：{novel.core_conflict.strip()}")
    if novel.style_guide and novel.style_guide.strip():
        lines.append(novel.style_guide.strip())
    else:
        lines.append("（没有额外风格规则）")
    return "\n".join(lines)


def _entities(session: Session, novel_id: str) -> list[StoryEntity]:
    stmt = (
        select(StoryEntity)
        .where(StoryEntity.novel_id == novel_id, StoryEntity.deleted_at.is_(None))
        .order_by(StoryEntity.created_at.asc(), StoryEntity.id.asc())
    )
    return list(session.scalars(stmt))


def _entity_names(session: Session, novel_id: str) -> dict[str, str]:
    return {entity.id: entity.name for entity in _entities(session, novel_id)}


def _latest_states(session: Session, entity_ids: list[str]) -> dict[str, EntityState]:
    if not entity_ids:
        return {}
    stmt = (
        select(EntityState)
        .where(EntityState.entity_id.in_(entity_ids))
        .order_by(EntityState.created_at.desc(), EntityState.id.desc())
    )
    found: dict[str, EntityState] = {}
    for state in session.scalars(stmt):
        if state.entity_id not in found:
            found[state.entity_id] = state
    return found


def _memory_gap_warnings(
    session: Session,
    *,
    novel_id: str,
    chapter_id: str | None,
) -> list[str]:
    """Say when compile has no rolling summary to inject.

    A current summary of the chapter being written is not earlier memory.
    Empty novels still compile; the warning is the signal that memory is absent.
    """

    rows = _summaries(session, novel_id)
    if not rows:
        return [EMPTY_MEMORY_WARNING]
    for summary, chapter in rows:
        if summary.status != "current" or summary.source_revision != chapter.revision:
            continue
        if chapter_id is not None and chapter.id == chapter_id:
            continue
        if summary.summary.strip():
            return []
    return [EARLIER_SUMMARY_WARNING]


def _summaries(session: Session, novel_id: str) -> list[tuple[ChapterSummary, Chapter]]:
    stmt = (
        select(ChapterSummary, Chapter)
        .join(Chapter, Chapter.id == ChapterSummary.chapter_id)
        .where(Chapter.novel_id == novel_id, Chapter.deleted_at.is_(None))
        .order_by(ChapterSummary.created_at.asc(), ChapterSummary.id.asc())
    )
    return list(session.execute(stmt).all())


def _related_events(
    session: Session,
    novel_id: str,
    instruction: str,
    selection_text: str,
    chapter_text: str,
) -> list[StoryEvent]:
    keys = _keywords(f"{instruction}\n{selection_text}\n{chapter_text[:400]}")
    if not keys:
        return []
    clauses = [
        StoryEvent.description.like(_like(key), escape="\\")
        | StoryEvent.evidence_quote.like(_like(key), escape="\\")
        for key in keys
    ]
    stmt = (
        select(StoryEvent)
        .where(
            StoryEvent.novel_id == novel_id,
            StoryEvent.deleted_at.is_(None),
            or_(*clauses),
        )
        .order_by(StoryEvent.created_at.asc(), StoryEvent.id.asc())
        .limit(8)
    )
    return list(session.scalars(stmt))


def _name_hit(entity: StoryEntity, haystack: str) -> str | None:
    folded = haystack.casefold()
    name = entity.name.strip()
    if len(name) >= 2 and (name in haystack or name.casefold() in folded):
        return "name"
    for alias in _strings(entity.aliases):
        if len(alias) >= 2 and (alias in haystack or alias.casefold() in folded):
            return "alias"
    return None


def _names(entity: StoryEntity) -> list[str]:
    return [entity.name, *_strings(entity.aliases)]


def _keywords(text: str) -> list[str]:
    found: list[str] = []
    for token in _CJK_KEYWORD.findall(text):
        if token not in found:
            found.append(token)
        if len(found) >= 6:
            break
    return found


def _like(keyword: str) -> str:
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _reading_order(volumes: list[Volume], chapters: list[Chapter]) -> list[Chapter]:
    ordered = sorted(
        [chapter for chapter in chapters if chapter.volume_id is None],
        key=lambda chapter: (chapter.sort_order, chapter.id),
    )
    for volume in sorted(volumes, key=lambda item: (item.sort_order, item.id)):
        ordered.extend(
            sorted(
                [chapter for chapter in chapters if chapter.volume_id == volume.id],
                key=lambda chapter: (chapter.sort_order, chapter.id),
            )
        )
    return ordered


def _neighbor(chapters: list[Chapter], chapter_id: str, offset: int) -> Chapter | None:
    index = next((item for item, chapter in enumerate(chapters) if chapter.id == chapter_id), None)
    if index is None:
        return None
    target = index + offset
    if target < 0 or target >= len(chapters):
        return None
    return chapters[target]


def _distance(chapters: list[Chapter], current_id: str | None, other_id: str) -> int:
    if current_id is None:
        return 10
    current_index = next(
        (item for item, chapter in enumerate(chapters) if chapter.id == current_id),
        None,
    )
    other_index = next(
        (item for item, chapter in enumerate(chapters) if chapter.id == other_id),
        None,
    )
    if current_index is None or other_index is None:
        return 10
    return abs(current_index - other_index)


def _tail(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= 500:
        return stripped
    return stripped[-500:]


def _shrunk(text: str) -> str:
    if len(text) <= _SHRINK_LIMIT:
        return text
    return text[:_SHRINK_LIMIT].rstrip() + "…"


def _candidate_length(candidates: list[_Candidate]) -> int:
    body = "\n\n".join(item.content for item in candidates if item.content.strip())
    return len(body)


def _included_length(items: list[ContextItem]) -> int:
    body = "\n\n".join(item.content for item in items if item.included and item.content.strip())
    return len(body)


def _add_line(lines: list[str], label: str, value: str | None) -> None:
    if value and value.strip():
        lines.append(f"{label}：{value.strip()}")


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _entity_label(entity_type: str) -> str:
    labels = {
        "character": "人物",
        "location": "地点",
        "organization": "组织",
        "item": "物品",
        "rule": "规则",
        "other": "其他",
    }
    return labels.get(entity_type, "其他")


def _context_hash(compiled: CompiledContext) -> str:
    payload = {
        "budget": compiled.budget,
        "compiler_version": compiled.compiler_version,
        "items": [
            {
                "content": item.content,
                "id": item.id,
                "included": item.included,
                "source_id": item.source_id,
                "source_revision": item.source_revision,
                "source_type": item.source_type,
            }
            for item in compiled.items
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _legacy_context(
    task_type: str,
    novel_id: str,
    chapter_id: str | None,
    snapshot: dict[str, object],
) -> CompiledContext:
    target = snapshot.get("target_revision")
    return CompiledContext(
        task_type=task_type,
        novel_id=novel_id,
        chapter_id=chapter_id,
        target_revision=target if isinstance(target, int) else None,
        items=[],
        total_token_estimate=0,
        budget=0,
        warnings=["当时只保存了整段提示，没有条目级来源。"],
        compiler_version="",
        context_hash="",
        legacy=True,
    )


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            name = str(key)
            if name.casefold() in _SECRET_KEYS:
                continue
            cleaned[name] = _redact_value(item)
        return cleaned
    return value


def _shrink_stored_item(item: object, *, drop_excluded: bool) -> object:
    if not isinstance(item, dict):
        return item
    copied = dict(item)
    included = copied.get("included") is True
    content = copied.get("content")
    if not isinstance(content, str):
        return copied
    if drop_excluded and not included:
        copied["content"] = ""
        return copied
    if len(content) > 500:
        copied["content"] = content[:500] + "…（快照已缩短）"
    return copied


def _encoded_length(payload: dict[str, object]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str))


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
