"""Store suspected quality issues and optional repair candidates.

Running a check writes issue rows only. Generating a candidate writes candidate
rows only. The manuscript and formal memory change only when the author accepts
a candidate, and that path reuses the existing revision lock.
"""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gateway import enabled_default, latest_enabled
from app.ai.prompts import build_quality_model_prompt, build_repair_model_prompt
from app.ai.provider import ProviderError
from app.core.content import apply_candidate_text, document_to_text
from app.core.errors import (
    InvalidReference,
    ModelConfigInvalid,
    NotFound,
    ProviderRequestFailed,
    RevisionConflict,
    TaskStateError,
)
from app.models.ai import ModelConfig
from app.models.catalog import Chapter
from app.models.memory import EntityRelation, EntityState, StoryEntity, StoryEvent
from app.models.planning import ChapterOutline, SceneCard, StoryArc
from app.models.quality import Foreshadowing, QualityIssue, QualityRepairCandidate
from app.repositories import catalog as catalog_repo
from app.schemas.catalog import ChapterResponse
from app.schemas.quality import (
    FindingClass,
    IssueStatus,
    IssueType,
    QualityCheckRequest,
    QualityCheckResponse,
    QualityEvidence,
    QualityIssueResponse,
    QualityProviderMode,
    QualityRef,
    RepairAcceptRequest,
    RepairApplyMode,
    RepairCandidateResponse,
    RepairDecisionResponse,
    RepairGenerateRequest,
    RepairListResponse,
    RepairStatus,
    Severity,
)
from app.services.catalog import apply_accepted_candidate
from app.services.conflicts import _endpoint as model_endpoint
from app.services.conflicts import _public_provider_error, generate_conflict_text
from app.services.quality_repairs import RepairDraft, model_repairs, rule_repairs
from app.services.quality_rules import (
    MODEL_VERSION,
    RULE_VERSION,
    ChapterMaterial,
    Evidence,
    QualityFinding,
    QualityMaterials,
    materials_from_mapping,
    model_findings_from_payload,
    run_rules,
)

logger = logging.getLogger("app.quality.issues")

_OPEN_STATUSES = ("pending", "confirmed", "deferred")
_ISSUE_TYPES = {
    "fact_continuity",
    "time_continuity",
    "character_continuity",
    "foreshadowing",
    "outline_execution",
    "text_surface",
}
_SEVERITIES = {"low", "medium", "high"}
_ISSUE_STATUSES = {
    "pending",
    "confirmed",
    "ignored",
    "fixed",
    "expired",
    "deferred",
    "intentional",
}
_PROVIDER_MODES = {"rule", "mock", "openai_compatible"}
_APPLY_MODES = {"replace_selection", "append"}
_REPAIR_STATUSES = {"proposed", "accepted", "rejected", "conflict"}


def list_quality_issues(
    session: Session,
    novel_id: str,
    *,
    status: str | None,
    chapter_id: str | None,
    include_closed: bool,
) -> list[QualityIssueResponse]:
    _require_novel(session, novel_id)
    stmt = select(QualityIssue).where(QualityIssue.novel_id == novel_id)
    if status is not None:
        stmt = stmt.where(QualityIssue.status == status)
    elif not include_closed:
        stmt = stmt.where(QualityIssue.status.in_(_OPEN_STATUSES))
    if chapter_id is not None:
        stmt = stmt.where(QualityIssue.chapter_id == chapter_id)
    stmt = stmt.order_by(QualityIssue.updated_at.desc(), QualityIssue.id.asc())
    rows = list(session.scalars(stmt).all())
    return _responses(session, rows)


def get_quality_issue(session: Session, issue_id: str) -> QualityIssueResponse:
    row = session.get(QualityIssue, issue_id)
    if row is None:
        raise NotFound("质量问题不存在。")
    return _responses(session, [row])[0]


def update_quality_issue_status(
    session: Session,
    issue_id: str,
    status: str,
) -> QualityIssueResponse:
    row = session.get(QualityIssue, issue_id)
    if row is None:
        raise NotFound("质量问题不存在。")
    if status not in {"pending", "confirmed", "ignored", "deferred", "intentional"}:
        raise InvalidReference("只能把问题标成待处理、已确认、已忽略、延后或有意安排。")
    row.status = status
    row.updated_at = _now()
    session.commit()
    session.refresh(row)
    logger.info("quality issue status updated")
    return _responses(session, [row])[0]


def run_quality_check(
    session: Session,
    novel_id: str,
    payload: QualityCheckRequest,
) -> QualityCheckResponse:
    _require_novel(session, novel_id)
    if payload.chapter_id is not None:
        _require_chapter(session, novel_id, payload.chapter_id)
    materials = _load_materials(session, novel_id, payload.chapter_id)
    findings = run_rules(materials)
    mode, config, note = _resolve_model(session, payload.use_model, payload.model_config_id)
    analysis_version: str | None = None
    if mode == "openai_compatible" and config is not None:
        try:
            findings.extend(_model_findings(config, materials))
            analysis_version = MODEL_VERSION
            note = "已额外运行模型检查。模型结果不会覆盖规则结果。"
        except ProviderRequestFailed:
            mode = "rule"
            note = "模型检查没有完成，规则结果已保留。"
    elif mode == "mock":
        analysis_version = MODEL_VERSION
    expired, reopened = _sync(session, novel_id, materials.focus_chapter_id, findings)
    session.commit()
    issues = list_quality_issues(
        session,
        novel_id,
        status=None,
        chapter_id=payload.chapter_id,
        include_closed=False,
    )
    logger.info("quality check stored", extra={"count": len(issues), "mode": mode})
    return QualityCheckResponse(
        novel_id=novel_id,
        chapter_id=payload.chapter_id,
        provider_mode=_provider(mode),
        rule_version=RULE_VERSION,
        analysis_version=analysis_version,
        manuscript_changed=False,
        formal_memory_changed=False,
        issue_count=len(issues),
        expired_count=expired,
        reopened_count=reopened,
        issues=issues,
        message=_check_message(note, len(issues), expired, reopened),
        model_config_id=config.id if config is not None else None,
        model_name=config.model_name if config is not None else None,
    )


def generate_repairs(
    session: Session,
    issue_id: str,
    payload: RepairGenerateRequest,
) -> RepairListResponse:
    issue = session.get(QualityIssue, issue_id)
    if issue is None:
        raise NotFound("质量问题不存在。")
    if issue.status == "expired":
        raise TaskStateError("问题已过期，请先重新检查。")
    chapter = _require_chapter(session, issue.novel_id, issue.chapter_id)
    text = document_to_text(chapter.content if isinstance(chapter.content, dict) else {})
    drafts = rule_repairs(
        rule_id=issue.rule_id,
        chapter_text=text,
        snippet=issue.manuscript_snippet,
        evidence=_dicts(issue.evidence),
        related_refs=_dicts(issue.related_refs),
    )
    mode, config, note = _resolve_model(session, payload.use_model, payload.model_config_id)
    if mode == "openai_compatible" and config is not None:
        try:
            drafts.extend(_model_repairs(config, issue, text))
            note = "已额外向模型要了改写候选。这些候选还没有写入正文。"
        except ProviderRequestFailed:
            mode = "rule"
            note = "模型没有返回可用候选，规则建议已保留。正文没有改动。"
    elif mode == "mock":
        note = "模拟模型检查已启用，没有在规则之外另造改写。正文没有改动。"
    else:
        note = "已根据规则生成修复建议。正文和正式记忆都没有改动。"
    now = _now()
    for old in session.scalars(
        select(QualityRepairCandidate).where(
            QualityRepairCandidate.issue_id == issue.id,
            QualityRepairCandidate.status == "proposed",
        )
    ).all():
        old.status = "rejected"
        old.updated_at = now
        if "已被新的建议代替" not in old.rationale:
            old.rationale = f"{old.rationale} 已被新的建议代替。"[:800]
    target_revision = chapter.revision
    created: list[QualityRepairCandidate] = []
    for draft in drafts:
        row = _candidate_row(issue, draft, target_revision, now)
        session.add(row)
        created.append(row)
    session.commit()
    for row in created:
        session.refresh(row)
    logger.info("quality repairs suggested", extra={"count": len(created)})
    return RepairListResponse(
        issue_id=issue.id,
        manuscript_changed=False,
        formal_memory_changed=False,
        provider_mode=_provider(mode),
        candidates=[_candidate_response(row) for row in created],
        message=note,
    )


def accept_repair(
    session: Session,
    candidate_id: str,
    payload: RepairAcceptRequest,
) -> RepairDecisionResponse:
    candidate = session.get(QualityRepairCandidate, candidate_id)
    if candidate is None:
        raise NotFound("修复建议不存在。")
    if candidate.status != "proposed":
        raise TaskStateError("这份建议已经处理过。")
    if not candidate.applicable:
        raise InvalidReference("这份建议不能直接写入正文。请自行修改。")
    issue = session.get(QualityIssue, candidate.issue_id)
    if issue is None:
        raise NotFound("质量问题不存在。")
    if issue.status == "expired":
        raise TaskStateError("问题已过期，请先重新检查。")
    chapter = _require_chapter(session, issue.novel_id, candidate.chapter_id)
    if chapter.novel_id != candidate.novel_id:
        raise InvalidReference("修复建议和章节不属于同一本作品。")
    if payload.target_revision != chapter.revision or chapter.revision != candidate.target_revision:
        _mark_conflict(session, candidate.id, expire_issue=False)
        raise RevisionConflict("目标修订已变化，没有覆盖新正文。请重新检查后再决定。")
    document = chapter.content if isinstance(chapter.content, dict) else {}
    text = document_to_text(document)
    if candidate.apply_mode == "replace_selection":
        snippet = candidate.original_snippet
        if text.count(snippet) != 1:
            _mark_conflict(session, candidate.id, expire_issue=snippet not in text)
            raise RevisionConflict("定位已过期或不再唯一，没有覆盖新正文。请重新检查。")
        updated = apply_candidate_text(
            document,
            candidate.replacement_text,
            mode="replace_selection",
            selection_text=snippet,
        )
    else:
        updated = apply_candidate_text(
            document,
            candidate.replacement_text,
            mode="append",
            selection_text="",
        )
    try:
        saved = apply_accepted_candidate(
            session,
            chapter.id,
            expected_revision=payload.target_revision,
            document=updated,
            change_note="采纳质量修复建议",
            repair_candidate_id=candidate.id,
            repair_issue_id=issue.id,
        )
    except RevisionConflict:
        _mark_conflict(session, candidate.id, expire_issue=False)
        raise RevisionConflict("目标修订已变化，没有覆盖新正文。请重新检查后再决定。") from None
    logger.info("quality repair accepted")
    refreshed_issue = _require_issue(session, issue.id)
    refreshed = _require_candidate(session, candidate.id)
    return RepairDecisionResponse(
        manuscript_changed=True,
        formal_memory_changed=False,
        candidate=_candidate_response(refreshed),
        issue=_responses(session, [refreshed_issue])[0],
        chapter=ChapterResponse.model_validate(saved),
        message="已采纳这条建议，并留下新的正文版本。正式设定没有被改写。可以重新检查。",
    )


def reject_repair(session: Session, candidate_id: str) -> RepairDecisionResponse:
    candidate = session.get(QualityRepairCandidate, candidate_id)
    if candidate is None:
        raise NotFound("修复建议不存在。")
    if candidate.status != "proposed":
        raise TaskStateError("这份建议已经处理过。")
    issue = _require_issue(session, candidate.issue_id)
    candidate.status = "rejected"
    candidate.updated_at = _now()
    session.commit()
    session.refresh(candidate)
    session.refresh(issue)
    logger.info("quality repair rejected")
    return RepairDecisionResponse(
        manuscript_changed=False,
        formal_memory_changed=False,
        candidate=_candidate_response(candidate),
        issue=_responses(session, [issue])[0],
        chapter=None,
        message="已放弃这条建议。正文和正式记忆都没有改动。",
    )


def _sync(
    session: Session,
    novel_id: str,
    focus_chapter_id: str | None,
    findings: list[QualityFinding],
) -> tuple[int, int]:
    existing = list(
        session.scalars(select(QualityIssue).where(QualityIssue.novel_id == novel_id)).all()
    )
    by_fingerprint = {row.fingerprint: row for row in existing}
    seen: set[str] = set()
    reopened = 0
    now = _now()
    for finding in findings:
        fingerprint = _fingerprint(novel_id, finding.fingerprint_key)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        row = by_fingerprint.get(fingerprint)
        if row is None:
            row = _new_issue(novel_id, finding, fingerprint, now)
            session.add(row)
            by_fingerprint[fingerprint] = row
            continue
        _refresh_issue(row, finding, now)
        if row.status == "fixed":
            row.status = "pending"
            row.recheck_count += 1
            reopened += 1
        elif row.status == "expired":
            row.status = "pending"
    expired = 0
    for row in existing:
        if row.fingerprint in seen:
            continue
        if focus_chapter_id is not None and row.chapter_id != focus_chapter_id:
            continue
        if row.status not in {"pending", "confirmed", "ignored"}:
            continue
        row.status = "expired"
        row.updated_at = now
        expired += 1
    return expired, reopened


def _new_issue(
    novel_id: str,
    finding: QualityFinding,
    fingerprint: str,
    now: datetime,
) -> QualityIssue:
    return QualityIssue(
        id=str(uuid.uuid4()),
        novel_id=novel_id,
        chapter_id=finding.chapter_id,
        issue_type=finding.issue_type,
        severity=finding.severity,
        confidence=_percent(finding.confidence),
        status="pending",
        finding_class=finding.finding_class,
        manuscript_snippet=finding.manuscript_snippet,
        target_revision=finding.target_revision,
        location_note=finding.location_note,
        evidence_status=finding.evidence_status,
        evidence=[_evidence_dump(item) for item in finding.evidence],
        related_refs=[_ref_dump(item) for item in finding.related_refs],
        rule_id=finding.rule_id,
        rule_version=RULE_VERSION if finding.rule_id != "model.suspected" else MODEL_VERSION,
        analysis_version=MODEL_VERSION if finding.rule_id == "model.suspected" else None,
        provider_mode="openai_compatible" if finding.rule_id == "model.suspected" else "rule",
        suggested_action=finding.suggested_action,
        fingerprint=fingerprint,
        fixed_revision=None,
        recheck_count=0,
        created_at=now,
        updated_at=now,
    )


def _refresh_issue(row: QualityIssue, finding: QualityFinding, now: datetime) -> None:
    row.chapter_id = finding.chapter_id
    row.issue_type = finding.issue_type
    row.finding_class = finding.finding_class
    row.severity = finding.severity
    row.confidence = _percent(finding.confidence)
    row.manuscript_snippet = finding.manuscript_snippet
    row.target_revision = finding.target_revision
    row.location_note = finding.location_note
    row.evidence_status = finding.evidence_status
    row.evidence = [_evidence_dump(item) for item in finding.evidence]
    row.related_refs = [_ref_dump(item) for item in finding.related_refs]
    row.rule_id = finding.rule_id
    row.rule_version = RULE_VERSION if finding.rule_id != "model.suspected" else MODEL_VERSION
    row.analysis_version = MODEL_VERSION if finding.rule_id == "model.suspected" else None
    row.provider_mode = "openai_compatible" if finding.rule_id == "model.suspected" else "rule"
    row.suggested_action = finding.suggested_action
    row.updated_at = now


def _load_materials(
    session: Session,
    novel_id: str,
    focus_chapter_id: str | None,
) -> QualityMaterials:
    ordered = _reading_order(session, novel_id)
    index = {chapter.id: position for position, chapter in enumerate(ordered)}
    chapters = tuple(
        ChapterMaterial(
            id=chapter.id,
            title=chapter.title,
            reading_index=index[chapter.id],
            revision=chapter.revision,
            text=document_to_text(chapter.content if isinstance(chapter.content, dict) else {}),
        )
        for chapter in ordered
    )
    payload: dict[str, object] = {
        "chapters": [
            {
                "id": item.id,
                "title": item.title,
                "reading_index": item.reading_index,
                "revision": item.revision,
                "text": item.text,
            }
            for item in chapters
        ],
        "events": [_event_payload(row) for row in _events(session, novel_id)],
        "states": [
            _state_payload(row, _entity_names(session, novel_id))
            for row in _states(session, novel_id)
        ],
        "relations": _relation_payloads(session, novel_id),
        "outlines": _outline_payloads(session, novel_id),
        "scenes": _scene_payloads(session, novel_id),
        "foreshadowing": _foreshadow_payloads(session, novel_id),
        "entities": _entity_payloads(session, novel_id),
        "arcs": _arc_payloads(session, novel_id),
        "focus_chapter_id": focus_chapter_id,
    }
    return materials_from_mapping(payload)


def _model_findings(config: ModelConfig, materials: QualityMaterials) -> list[QualityFinding]:
    known = _known_quotes(materials)
    evidence_lines = _evidence_lines(materials)
    chapters = [
        item
        for item in materials.chapters
        if materials.focus_chapter_id is None or item.id == materials.focus_chapter_id
    ]
    if materials.focus_chapter_id is None:
        chapters = chapters[:6]
    found: list[QualityFinding] = []
    for chapter in chapters:
        shown = ChapterMaterial(
            id=chapter.id,
            title=chapter.title,
            reading_index=chapter.reading_index,
            revision=chapter.revision,
            text=chapter.text[:8000],
        )
        prompt = build_quality_model_prompt(
            title=chapter.title,
            chapter_text=shown.text,
            evidence_lines=evidence_lines,
        )
        if shown.text.strip() == "":
            continue
        try:
            raw = generate_conflict_text(endpoint=model_endpoint(config), prompt=prompt)
            loaded = _load_object(raw)
        except ProviderError as exc:
            raise _public_provider_error(exc) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderRequestFailed(
                "MODEL_BAD_RESPONSE",
                "模型没有返回可解析的质量问题。正文和正式记忆都没有改动。",
                502,
            ) from exc
        found.extend(
            model_findings_from_payload(
                loaded.get("issues"),
                chapter=shown,
                known_quotes=known,
            )
        )
    return found


def _model_repairs(
    config: ModelConfig,
    issue: QualityIssue,
    chapter_text: str,
) -> list[RepairDraft]:
    prompt = build_repair_model_prompt(
        issue_summary=issue.suggested_action,
        snippet=issue.manuscript_snippet,
        chapter_text=chapter_text,
    )
    try:
        raw = generate_conflict_text(endpoint=model_endpoint(config), prompt=prompt)
        loaded = _load_object(raw)
    except ProviderError as exc:
        raise _public_provider_error(exc) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderRequestFailed(
            "MODEL_BAD_RESPONSE",
            "模型没有返回可解析的修复建议。正文和正式记忆都没有改动。",
            502,
        ) from exc
    drafts = model_repairs(
        loaded.get("candidates"),
        chapter_text=chapter_text,
        snippet=issue.manuscript_snippet,
    )
    return drafts


def _known_quotes(materials: QualityMaterials) -> dict[str, Evidence]:
    known: dict[str, Evidence] = {}
    for event in materials.events:
        quote = event.evidence_quote.strip()
        if quote and quote not in known:
            known[quote] = Evidence(
                "story_event",
                event.description or "已确认事实",
                quote,
                event.chapter_id,
                event.source_revision,
                event.id,
            )
    for state in materials.states:
        quote = (state.evidence_quote or "").strip()
        if quote and quote not in known:
            known[quote] = Evidence(
                "entity_state",
                state.entity_name,
                quote,
                state.chapter_id,
                state.source_revision,
                state.id,
            )
    for relation in materials.relations:
        quote = (relation.evidence_quote or "").strip()
        if quote and quote not in known:
            known[quote] = Evidence(
                "relation",
                relation.relation_type,
                quote,
                relation.source_chapter_id,
                relation.source_revision,
                relation.id,
            )
    return known


def _evidence_lines(materials: QualityMaterials) -> list[str]:
    lines: list[str] = []
    for event in materials.events:
        if event.evidence_quote.strip():
            lines.append(f"事实：{event.description}｜引用：{event.evidence_quote}")
    for state in materials.states:
        if state.evidence_quote:
            lines.append(f"状态：{state.entity_name}｜引用：{state.evidence_quote}")
    for relation in materials.relations:
        lines.append(f"关系：{relation.from_name}是{relation.to_name}的{relation.relation_type}")
    return lines[:40]


def _resolve_model(
    session: Session,
    use_model: bool,
    model_config_id: str | None,
) -> tuple[str, ModelConfig | None, str]:
    if not use_model:
        return "rule", None, "模型检查未启用。"
    if model_config_id:
        config = session.get(ModelConfig, model_config_id)
        if config is None:
            raise NotFound("模型配置不存在。")
        if not config.is_enabled:
            raise ModelConfigInvalid("这个模型配置已停用。")
        if config.provider_type == "mock":
            return "mock", config, "已启用模拟模型检查，没有访问外部模型。"
        return "openai_compatible", config, ""
    default = enabled_default(session)
    if default is not None:
        if default.provider_type == "mock":
            return "mock", default, "已启用模拟模型检查，没有访问外部模型。"
        return "openai_compatible", default, ""
    external = latest_enabled(session, "openai_compatible")
    if external is not None:
        return "openai_compatible", external, ""
    mock = session.scalars(
        select(ModelConfig).where(
            ModelConfig.is_enabled.is_(True),
            ModelConfig.provider_type == "mock",
        )
    ).first()
    if mock is not None:
        return "mock", mock, "已启用模拟模型检查，没有访问外部模型。"
    return "rule", None, "没有可用模型，只运行了规则检查。"


def _candidate_row(
    issue: QualityIssue,
    draft: RepairDraft,
    target_revision: int,
    now: datetime,
) -> QualityRepairCandidate:
    provider = draft.provider_mode if draft.provider_mode in _PROVIDER_MODES else "rule"
    mode = draft.apply_mode if draft.apply_mode in _APPLY_MODES else "replace_selection"
    return QualityRepairCandidate(
        id=str(uuid.uuid4()),
        issue_id=issue.id,
        novel_id=issue.novel_id,
        chapter_id=issue.chapter_id,
        target_revision=target_revision,
        apply_mode=mode,
        applicable=draft.applicable,
        original_snippet=draft.original_snippet,
        replacement_text=draft.replacement_text,
        rationale=draft.rationale,
        diff_preview=draft.diff_preview,
        provider_mode=provider,
        prompt_version=draft.prompt_version,
        status="proposed",
        created_at=now,
        updated_at=now,
    )


def _mark_conflict(session: Session, candidate_id: str, *, expire_issue: bool) -> None:
    session.rollback()
    candidate = session.get(QualityRepairCandidate, candidate_id)
    if candidate is None:
        return
    now = _now()
    if candidate.status == "proposed":
        candidate.status = "conflict"
        candidate.updated_at = now
    if expire_issue:
        issue = session.get(QualityIssue, candidate.issue_id)
        if issue is not None and issue.status in {"pending", "confirmed", "ignored"}:
            issue.status = "expired"
            issue.updated_at = now
    session.commit()


def _responses(session: Session, rows: list[QualityIssue]) -> list[QualityIssueResponse]:
    if not rows:
        return []
    titles = {
        chapter.id: chapter.title
        for chapter in catalog_repo.list_chapters(session, rows[0].novel_id)
    }
    issue_ids = [row.id for row in rows]
    candidates = list(
        session.scalars(
            select(QualityRepairCandidate)
            .where(QualityRepairCandidate.issue_id.in_(issue_ids))
            .order_by(QualityRepairCandidate.created_at.asc(), QualityRepairCandidate.id.asc())
        ).all()
    )
    grouped: dict[str, list[RepairCandidateResponse]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.issue_id, []).append(_candidate_response(candidate))
    return [_issue_response(row, titles, grouped.get(row.id, [])) for row in rows]


def _issue_response(
    row: QualityIssue,
    titles: dict[str, str],
    candidates: list[RepairCandidateResponse],
) -> QualityIssueResponse:
    return QualityIssueResponse(
        id=row.id,
        novel_id=row.novel_id,
        chapter_id=row.chapter_id,
        chapter_title=titles.get(row.chapter_id, ""),
        issue_type=_issue_type(row.issue_type),
        severity=_severity(row.severity),
        confidence=round(row.confidence / 100, 2),
        status=_issue_status(row.status),
        finding_class=_finding_class(row.finding_class),
        manuscript_snippet=row.manuscript_snippet,
        target_revision=row.target_revision,
        location_note=row.location_note,
        evidence_status="insufficient" if row.evidence_status == "insufficient" else "sufficient",
        evidence=_evidence_responses(_dicts(row.evidence), titles),
        related_refs=_ref_responses(_dicts(row.related_refs)),
        rule_id=row.rule_id,
        rule_version=row.rule_version,
        analysis_version=row.analysis_version,
        provider_mode=_provider(row.provider_mode),
        suggested_action=row.suggested_action,
        fixed_revision=row.fixed_revision,
        recheck_count=row.recheck_count,
        candidates=candidates,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _candidate_response(row: QualityRepairCandidate) -> RepairCandidateResponse:
    return RepairCandidateResponse(
        id=row.id,
        issue_id=row.issue_id,
        novel_id=row.novel_id,
        chapter_id=row.chapter_id,
        target_revision=row.target_revision,
        apply_mode=_apply_mode(row.apply_mode),
        applicable=bool(row.applicable),
        original_snippet=row.original_snippet,
        replacement_text=row.replacement_text,
        rationale=row.rationale,
        diff_preview=row.diff_preview,
        provider_mode=_provider(row.provider_mode),
        prompt_version=row.prompt_version,
        status=_repair_status(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _evidence_responses(
    rows: list[dict[str, object]],
    titles: dict[str, str],
) -> list[QualityEvidence]:
    evidence: list[QualityEvidence] = []
    for item in rows:
        chapter_id = _text(item, "source_chapter_id")
        evidence.append(
            QualityEvidence(
                kind=_text(item, "kind") or "note",
                label=_text(item, "label") or "",
                quote=_text(item, "quote"),
                source_chapter_id=chapter_id,
                source_chapter_title=titles.get(chapter_id or "", ""),
                source_revision=_int(item, "source_revision"),
                ref_id=_text(item, "ref_id"),
            )
        )
    return evidence


def _ref_responses(rows: list[dict[str, object]]) -> list[QualityRef]:
    refs: list[QualityRef] = []
    for item in rows:
        ref_id = _text(item, "ref_id")
        if ref_id is None:
            continue
        refs.append(
            QualityRef(
                kind=_text(item, "kind") or "note",
                ref_id=ref_id,
                label=_text(item, "label") or "",
            )
        )
    return refs


def _reading_order(session: Session, novel_id: str) -> list[Chapter]:
    volumes = catalog_repo.list_volumes(session, novel_id)
    chapters = catalog_repo.list_chapters(session, novel_id)
    grouped: dict[str | None, list[Chapter]] = {}
    for chapter in chapters:
        grouped.setdefault(chapter.volume_id, []).append(chapter)
    ordered: list[Chapter] = []
    ordered.extend(grouped.get(None, []))
    seen = {chapter.id for chapter in ordered}
    for volume in volumes:
        for chapter in grouped.get(volume.id, []):
            if chapter.id not in seen:
                ordered.append(chapter)
                seen.add(chapter.id)
    for chapter in chapters:
        if chapter.id not in seen:
            ordered.append(chapter)
    return ordered


def _events(session: Session, novel_id: str) -> list[StoryEvent]:
    return list(
        session.scalars(
            select(StoryEvent).where(
                StoryEvent.novel_id == novel_id,
                StoryEvent.deleted_at.is_(None),
                StoryEvent.certainty == "confirmed",
            )
        ).all()
    )


def _states(session: Session, novel_id: str) -> list[EntityState]:
    return list(
        session.scalars(
            select(EntityState)
            .join(StoryEntity, StoryEntity.id == EntityState.entity_id)
            .where(StoryEntity.novel_id == novel_id, StoryEntity.deleted_at.is_(None))
        ).all()
    )


def _entity_names(session: Session, novel_id: str) -> dict[str, str]:
    rows = session.scalars(
        select(StoryEntity).where(
            StoryEntity.novel_id == novel_id,
            StoryEntity.deleted_at.is_(None),
        )
    ).all()
    return {row.id: row.name for row in rows}


def _event_payload(row: StoryEvent) -> dict[str, object]:
    return {
        "id": row.id,
        "chapter_id": row.chapter_id,
        "description": row.description,
        "evidence_quote": row.evidence_quote,
        "event_time_text": row.event_time_text,
        "participants": _string_list(row.participants),
        "source_revision": row.source_revision,
    }


def _state_payload(row: EntityState, names: dict[str, str]) -> dict[str, object]:
    values: dict[str, str] = {}
    if isinstance(row.state_data, dict):
        for key, raw in row.state_data.items():
            if isinstance(key, str) and isinstance(raw, str):
                values[key] = raw
    return {
        "id": row.id,
        "entity_id": row.entity_id,
        "entity_name": names.get(row.entity_id, ""),
        "chapter_id": row.chapter_id,
        "values": values,
        "evidence_quote": row.evidence_quote,
        "valid_from_text": row.valid_from_text,
        "valid_until_text": row.valid_until_text,
        "source_revision": row.source_revision,
    }


def _relation_payloads(session: Session, novel_id: str) -> list[dict[str, object]]:
    names = _entity_names(session, novel_id)
    rows = session.scalars(
        select(EntityRelation).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.deleted_at.is_(None),
            EntityRelation.status == "active",
        )
    ).all()
    payloads: list[dict[str, object]] = []
    for row in rows:
        payloads.append(
            {
                "id": row.id,
                "from_name": names.get(row.from_entity_id, ""),
                "to_name": names.get(row.to_entity_id, ""),
                "relation_type": row.relation_type,
                "evidence_quote": row.evidence_quote,
                "source_chapter_id": row.source_chapter_id,
                "source_revision": row.source_revision,
            }
        )
    return payloads


def _outline_payloads(session: Session, novel_id: str) -> list[dict[str, object]]:
    rows = session.scalars(
        select(ChapterOutline).where(
            ChapterOutline.novel_id == novel_id,
            ChapterOutline.status == "confirmed",
        )
    ).all()
    return [
        {
            "id": row.id,
            "chapter_id": row.chapter_id,
            "required_events": row.required_events,
            "must_advance": row.must_advance,
            "forbidden_reveals": row.forbidden_reveals,
        }
        for row in rows
    ]


def _scene_payloads(session: Session, novel_id: str) -> list[dict[str, object]]:
    rows = session.scalars(
        select(SceneCard).where(SceneCard.novel_id == novel_id, SceneCard.status == "confirmed")
    ).all()
    return [
        {
            "id": row.id,
            "chapter_id": row.chapter_id,
            "must_convey": row.must_convey,
            "must_not_reveal": row.must_not_reveal,
        }
        for row in rows
    ]


def _foreshadow_payloads(session: Session, novel_id: str) -> list[dict[str, object]]:
    rows = session.scalars(select(Foreshadowing).where(Foreshadowing.novel_id == novel_id)).all()
    return [
        {
            "id": row.id,
            "description": row.description,
            "status": row.status,
            "introduced_chapter_id": row.introduced_chapter_id,
            "payoff_chapter_id": row.payoff_chapter_id,
            "evidence_quote": row.evidence_quote,
            "event_time_text": row.event_time_text,
            "character_discovered_text": row.character_discovered_text,
            "reader_revealed_text": row.reader_revealed_text,
        }
        for row in rows
    ]


def _entity_payloads(session: Session, novel_id: str) -> list[dict[str, object]]:
    rows = session.scalars(
        select(StoryEntity).where(
            StoryEntity.novel_id == novel_id,
            StoryEntity.deleted_at.is_(None),
        )
    ).all()
    result: list[dict[str, object]] = []
    for row in rows:
        result.append(
            {
                "id": row.id,
                "name": row.name,
                "aliases": _string_list(row.aliases),
                "entity_type": row.entity_type,
                "profile": row.profile if isinstance(row.profile, dict) else {},
            }
        )
    return result


def _require_novel(session: Session, novel_id: str) -> None:
    if catalog_repo.get_novel(session, novel_id) is None:
        raise NotFound("作品不存在。")


def _require_chapter(session: Session, novel_id: str, chapter_id: str) -> Chapter:
    chapter = catalog_repo.get_chapter(session, chapter_id)
    if chapter is None or chapter.deleted_at is not None or chapter.novel_id != novel_id:
        raise InvalidReference("章节不存在，或不属于这本作品。")
    return chapter


def _require_issue(session: Session, issue_id: str) -> QualityIssue:
    session.expire_all()
    row = session.get(QualityIssue, issue_id)
    if row is None:
        raise NotFound("质量问题不存在。")
    return row


def _require_candidate(session: Session, candidate_id: str) -> QualityRepairCandidate:
    row = session.get(QualityRepairCandidate, candidate_id)
    if row is None:
        raise NotFound("修复建议不存在。")
    return row


def _check_message(note: str, issue_count: int, expired: int, reopened: int) -> str:
    return (
        f"规则检查完成，当前有 {issue_count} 条待处理或已确认的疑似问题。"
        f"{note}"
        f"本轮把 {expired} 条不再成立的问题标为已过期，"
        f"把 {reopened} 条已修复后又出现的问题重新打开。"
        "正文和正式记忆都没有改动。"
    )


def _fingerprint(novel_id: str, key: str) -> str:
    return hashlib.sha256(f"{novel_id}\n{key}".encode()).hexdigest()[:40]


def _percent(confidence: float) -> int:
    return max(0, min(100, int(round(confidence * 100))))


def _evidence_dump(item: Evidence) -> dict[str, object]:
    return {
        "kind": item.kind,
        "label": item.label,
        "quote": item.quote,
        "source_chapter_id": item.source_chapter_id,
        "source_revision": item.source_revision,
        "ref_id": item.ref_id,
    }


def _ref_dump(item: object) -> dict[str, object]:
    return {
        "kind": str(getattr(item, "kind", "")),
        "ref_id": str(getattr(item, "ref_id", "")),
        "label": str(getattr(item, "label", "")),
    }


def _dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            rows.append({str(key): item[key] for key in item})
    return rows


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(item: dict[str, object], key: str) -> str | None:
    value = item.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _int(item: dict[str, object], key: str) -> int | None:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _load_object(raw: str) -> dict[str, object]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no json object")
    loaded = json.loads(raw[start : end + 1])
    if not isinstance(loaded, dict):
        raise ValueError("json is not an object")
    return cast(dict[str, object], loaded)


def _issue_type(value: str) -> IssueType:
    if value in _ISSUE_TYPES:
        return cast(IssueType, value)
    return "fact_continuity"


def _finding_class(value: str) -> FindingClass:
    if value in {"deterministic", "suspected", "creative_risk"}:
        return cast(FindingClass, value)
    return "suspected"


def _arc_payloads(session: Session, novel_id: str) -> list[dict[str, object]]:
    rows = session.scalars(select(StoryArc).where(StoryArc.novel_id == novel_id)).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "summary": row.summary,
            "status": row.status,
            "thread_visibility": row.thread_visibility,
        }
        for row in rows
    ]


def _issue_status(value: str) -> IssueStatus:
    if value in _ISSUE_STATUSES:
        return cast(IssueStatus, value)
    return "pending"


def _severity(value: str) -> Severity:
    if value in _SEVERITIES:
        return cast(Severity, value)
    return "medium"


def _provider(value: str) -> QualityProviderMode:
    if value in _PROVIDER_MODES:
        return cast(QualityProviderMode, value)
    return "rule"


def _apply_mode(value: str) -> RepairApplyMode:
    if value in _APPLY_MODES:
        return cast(RepairApplyMode, value)
    return "replace_selection"


def _repair_status(value: str) -> RepairStatus:
    if value in _REPAIR_STATUSES:
        return cast(RepairStatus, value)
    return "proposed"


def _now() -> datetime:
    return datetime.now(UTC)
