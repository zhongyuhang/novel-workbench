"""Find materials that still refer to a confirmed setting.

The scan only reads. It does not change the manuscript or formal memory.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.content import document_to_text
from app.core.errors import InvalidReference, NotFound
from app.models.catalog import Chapter
from app.models.memory import EntityRelation, EntityState, StoryEntity, StoryEvent
from app.models.planning import ChapterOutline, SceneCard, StoryArc
from app.models.quality import Foreshadowing, QualityIssue
from app.repositories import catalog as catalog_repo
from app.schemas.memory import AffectedMaterial, ImpactKind, MaterialImpactResponse

_KINDS = {"entity", "relation", "event", "foreshadowing", "story_arc"}


def material_impact(
    session: Session,
    novel_id: str,
    kind: str,
    target_id: str,
) -> MaterialImpactResponse:
    if catalog_repo.get_novel(session, novel_id) is None:
        raise NotFound("作品不存在。")
    if kind not in _KINDS:
        raise InvalidReference("还不能分析这种资料。")
    target_kind: ImpactKind = kind  # type: ignore[assignment]
    if kind == "entity":
        entity = _entity(session, novel_id, target_id)
        affected = _entity_impact(session, novel_id, entity)
        label = entity.name
    elif kind == "relation":
        relation = _relation(session, novel_id, target_id)
        affected = _relation_impact(session, novel_id, relation)
        label = relation.relation_type
    elif kind == "event":
        event = _event(session, novel_id, target_id)
        affected = _event_impact(session, novel_id, event)
        label = event.description[:80]
    elif kind == "foreshadowing":
        hook = _foreshadowing(session, novel_id, target_id)
        affected = _foreshadow_impact(session, novel_id, hook)
        label = hook.description[:80]
    else:
        arc = _arc(session, novel_id, target_id)
        affected = _arc_impact(session, novel_id, arc)
        label = arc.title
    affected.sort(key=lambda item: (item.kind, item.id))
    return MaterialImpactResponse(
        novel_id=novel_id,
        target_kind=target_kind,
        target_id=target_id,
        target_label=label,
        affected=affected,
        manuscript_changed=False,
        formal_memory_changed=False,
    )


def _entity_impact(session: Session, novel_id: str, entity: StoryEntity) -> list[AffectedMaterial]:
    names = [entity.name, *[alias for alias in _strings(entity.aliases) if alias]]
    found: list[AffectedMaterial] = []
    for relation in session.scalars(
        select(EntityRelation).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.deleted_at.is_(None),
            or_(
                EntityRelation.from_entity_id == entity.id,
                EntityRelation.to_entity_id == entity.id,
            ),
        )
    ).all():
        found.append(
            AffectedMaterial(
                kind="relation",
                id=relation.id,
                label=relation.relation_type,
                reason="关系的一端是这个设定",
            )
        )
    for state in session.scalars(
        select(EntityState).where(EntityState.entity_id == entity.id)
    ).all():
        found.append(
            AffectedMaterial(
                kind="entity_state",
                id=state.id,
                label=_state_label(state),
                reason="动态状态属于这个设定",
            )
        )
    for event in _events(session, novel_id):
        if _text_hits(f"{event.description}\n{event.evidence_quote}", names) or _name_in(
            _strings(event.participants), names
        ):
            found.append(
                AffectedMaterial(
                    kind="story_event",
                    id=event.id,
                    label=event.description[:80],
                    reason="事件写到了这个设定",
                )
            )
    for hook in _hooks(session, novel_id):
        blob = "\n".join(
            part
            for part in (
                hook.description,
                hook.evidence_quote,
                hook.event_time_text,
                hook.character_discovered_text,
                hook.reader_revealed_text,
            )
            if part
        )
        if _text_hits(blob, names):
            found.append(
                AffectedMaterial(
                    kind="foreshadowing",
                    id=hook.id,
                    label=hook.description[:80],
                    reason="伏笔文本提到了这个设定",
                )
            )
    for arc in _arcs(session, novel_id):
        if _text_hits(f"{arc.title}\n{arc.summary or ''}", names):
            found.append(
                AffectedMaterial(
                    kind="story_arc",
                    id=arc.id,
                    label=arc.title,
                    reason="故事线写到了这个设定",
                )
            )
    for chapter in catalog_repo.list_chapters(session, novel_id):
        text = document_to_text(chapter.content if isinstance(chapter.content, dict) else {})
        if _text_hits(text, names):
            found.append(
                AffectedMaterial(
                    kind="chapter",
                    id=chapter.id,
                    label=chapter.title,
                    reason="正文提到了这个设定",
                )
            )
    for scene in session.scalars(select(SceneCard).where(SceneCard.novel_id == novel_id)).all():
        people = _strings(scene.character_entity_ids)
        if entity.id in people or scene.location_entity_id == entity.id:
            found.append(
                AffectedMaterial(
                    kind="scene",
                    id=scene.id,
                    label=scene.goal or "场景",
                    reason="场景引用了这个设定",
                )
            )
    for outline in session.scalars(
        select(ChapterOutline).where(ChapterOutline.novel_id == novel_id)
    ).all():
        blob = "\n".join(
            part
            for part in (
                outline.goal,
                outline.must_advance,
                outline.required_events,
                outline.allowed_reveals,
                outline.forbidden_reveals,
                outline.ending_hook,
            )
            if part
        )
        if _text_hits(blob, names):
            found.append(
                AffectedMaterial(
                    kind="chapter_outline",
                    id=outline.id,
                    label=outline.goal or "章节大纲",
                    reason="章节大纲写到了这个设定",
                )
            )
    _issues(found, session, novel_id, names, entity.id)
    return found


def _relation_impact(
    session: Session,
    novel_id: str,
    relation: EntityRelation,
) -> list[AffectedMaterial]:
    found: list[AffectedMaterial] = []
    for entity_id, reason in (
        (relation.from_entity_id, "关系从这里指出"),
        (relation.to_entity_id, "关系指向这里"),
    ):
        entity = session.get(StoryEntity, entity_id)
        if entity is not None and entity.deleted_at is None:
            found.append(
                AffectedMaterial(kind="entity", id=entity.id, label=entity.name, reason=reason)
            )
    names = []
    for entity_id in (relation.from_entity_id, relation.to_entity_id):
        entity = session.get(StoryEntity, entity_id)
        if entity is not None:
            names.append(entity.name)
    for event in _events(session, novel_id):
        if names and all(name in event.participants or name in event.description for name in names):
            found.append(
                AffectedMaterial(
                    kind="story_event",
                    id=event.id,
                    label=event.description[:80],
                    reason="事件同时写到关系的两端",
                )
            )
    _issues(found, session, novel_id, [relation.relation_type], relation.id)
    return found


def _event_impact(session: Session, novel_id: str, event: StoryEvent) -> list[AffectedMaterial]:
    found: list[AffectedMaterial] = []
    chapter = session.get(Chapter, event.chapter_id)
    if chapter is not None and chapter.deleted_at is None and chapter.novel_id == novel_id:
        found.append(
            AffectedMaterial(
                kind="chapter",
                id=chapter.id,
                label=chapter.title,
                reason="事件来自这一章",
            )
        )
    names = _strings(event.participants)
    if names:
        for entity in session.scalars(
            select(StoryEntity).where(
                StoryEntity.novel_id == novel_id,
                StoryEntity.deleted_at.is_(None),
                StoryEntity.name.in_(names),
            )
        ).all():
            found.append(
                AffectedMaterial(
                    kind="entity",
                    id=entity.id,
                    label=entity.name,
                    reason="事件的参与者和这个设定同名",
                )
            )
    _issues(found, session, novel_id, [event.description[:40]], event.id)
    return found


def _foreshadow_impact(
    session: Session,
    novel_id: str,
    hook: Foreshadowing,
) -> list[AffectedMaterial]:
    found: list[AffectedMaterial] = []
    for chapter_id, reason in (
        (hook.introduced_chapter_id, "伏笔埋在这一章"),
        (hook.payoff_chapter_id, "伏笔计划在这一章回收"),
    ):
        if chapter_id is None:
            continue
        chapter = session.get(Chapter, chapter_id)
        if chapter is not None and chapter.deleted_at is None and chapter.novel_id == novel_id:
            found.append(
                AffectedMaterial(kind="chapter", id=chapter.id, label=chapter.title, reason=reason)
            )
    names = [hook.description[:12]] if len(hook.description) >= 2 else []
    if names:
        for entity in session.scalars(
            select(StoryEntity).where(
                StoryEntity.novel_id == novel_id,
                StoryEntity.deleted_at.is_(None),
            )
        ).all():
            if entity.name and entity.name in hook.description:
                found.append(
                    AffectedMaterial(
                        kind="entity",
                        id=entity.id,
                        label=entity.name,
                        reason="伏笔描述提到了这个设定",
                    )
                )
    _issues(found, session, novel_id, [hook.description[:40]], hook.id)
    return found


def _arc_impact(session: Session, novel_id: str, arc: StoryArc) -> list[AffectedMaterial]:
    found: list[AffectedMaterial] = []
    for chapter in catalog_repo.list_chapters(session, novel_id):
        text = document_to_text(chapter.content if isinstance(chapter.content, dict) else {})
        if arc.title and arc.title in text:
            found.append(
                AffectedMaterial(
                    kind="chapter",
                    id=chapter.id,
                    label=chapter.title,
                    reason="正文出现了这条故事线的标题",
                )
            )
    for hook in _hooks(session, novel_id):
        if arc.title and arc.title in hook.description:
            found.append(
                AffectedMaterial(
                    kind="foreshadowing",
                    id=hook.id,
                    label=hook.description[:80],
                    reason="伏笔描述出现了这条故事线的标题",
                )
            )
    return found


def _issues(
    found: list[AffectedMaterial],
    session: Session,
    novel_id: str,
    needles: list[str],
    ref_id: str,
) -> None:
    useful = [item for item in needles if len(item) >= 2]
    rows = session.scalars(select(QualityIssue).where(QualityIssue.novel_id == novel_id)).all()
    for issue in rows:
        blob = "\n".join(
            (
                issue.manuscript_snippet,
                issue.location_note or "",
                str(issue.evidence),
                str(issue.related_refs),
            )
        )
        if ref_id in blob or _text_hits(blob, useful):
            found.append(
                AffectedMaterial(
                    kind="quality_issue",
                    id=issue.id,
                    label=issue.rule_id,
                    reason="质量问题引用了这条资料",
                )
            )


def _events(session: Session, novel_id: str) -> list[StoryEvent]:
    return list(
        session.scalars(
            select(StoryEvent).where(
                StoryEvent.novel_id == novel_id,
                StoryEvent.deleted_at.is_(None),
            )
        ).all()
    )


def _hooks(session: Session, novel_id: str) -> list[Foreshadowing]:
    rows = session.scalars(select(Foreshadowing).where(Foreshadowing.novel_id == novel_id)).all()
    return list(rows)


def _arcs(session: Session, novel_id: str) -> list[StoryArc]:
    return list(session.scalars(select(StoryArc).where(StoryArc.novel_id == novel_id)).all())


def _entity(session: Session, novel_id: str, entity_id: str) -> StoryEntity:
    row = session.get(StoryEntity, entity_id)
    if row is None or row.deleted_at is not None or row.novel_id != novel_id:
        raise NotFound("设定不存在。")
    return row


def _relation(session: Session, novel_id: str, relation_id: str) -> EntityRelation:
    row = session.get(EntityRelation, relation_id)
    if row is None or row.deleted_at is not None or row.novel_id != novel_id:
        raise NotFound("关系不存在。")
    return row


def _event(session: Session, novel_id: str, event_id: str) -> StoryEvent:
    row = session.get(StoryEvent, event_id)
    if row is None or row.deleted_at is not None or row.novel_id != novel_id:
        raise NotFound("事件不存在。")
    return row


def _foreshadowing(session: Session, novel_id: str, hook_id: str) -> Foreshadowing:
    row = session.get(Foreshadowing, hook_id)
    if row is None or row.novel_id != novel_id:
        raise NotFound("伏笔不存在。")
    return row


def _arc(session: Session, novel_id: str, arc_id: str) -> StoryArc:
    row = session.get(StoryArc, arc_id)
    if row is None or row.novel_id != novel_id:
        raise NotFound("故事线不存在。")
    return row


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text_hits(text: str, names: list[str]) -> bool:
    return any(name and name in text for name in names)


def _name_in(values: list[str], names: list[str]) -> bool:
    return any(name in values for name in names)


def _state_label(state: EntityState) -> str:
    data = state.state_data if isinstance(state.state_data, dict) else {}
    for key in ("summary", "身份", "位置", "伤势"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return "动态状态"
