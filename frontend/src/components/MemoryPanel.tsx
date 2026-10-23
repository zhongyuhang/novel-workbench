import { useEffect, useState } from "react";
import { listModelConfigs } from "../api/models.ts";
import {
  acceptProposal,
  analyzeChapter,
  createEntity,
  createEntityState,
  createRelation,
  deferProposal,
  deleteRelation,
  listChapterSummaries,
  listEntities,
  listEvents,
  listProposals,
  listRelations,
  markIntentionalProposal,
  materialImpact,
  rejectProposal,
  revertProposal,
  updateEntity,
  type AnalysisScope,
  type Certainty,
  type ChapterSummaryRecord,
  type EntityRelation,
  type EntityState,
  type EntityStatus,
  type EntityType,
  type EntityWrite,
  type MemoryProposal,
  type ProposalType,
  type RelationStatus,
  type StoryEntity,
  type StoryEventRecord,
} from "../api/memory.ts";
import { ApiError, type ModelConfig } from "../api/types.ts";
import { registerMemoryAnalyze } from "../features/memory/analyzeBridge.ts";

type BibleChapter = {
  id: string;
  title: string;
};

type MemoryPanelProps = {
  novelId: string;
  activeChapterId: string | null;
  activeRevision: number | null;
  activeTitle: string | null;
  editorDirty: boolean;
  chapters?: BibleChapter[];
  materialVersion?: number;
};

const ENTITY_TYPES: Array<{ value: EntityType; label: string }> = [
  { value: "character", label: "人物" },
  { value: "location", label: "地点" },
  { value: "organization", label: "组织" },
  { value: "item", label: "物品" },
  { value: "rule", label: "规则" },
  { value: "other", label: "其他" },
];

const ENTITY_STATUS: Array<{ value: EntityStatus; label: string }> = [
  { value: "active", label: "启用" },
  { value: "inactive", label: "停用" },
  { value: "unknown", label: "未知" },
];

const RELATION_STATUS: Array<{ value: RelationStatus; label: string }> = [
  { value: "active", label: "启用" },
  { value: "ended", label: "已结束" },
  { value: "unknown", label: "未知" },
];

const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "", label: "全部状态" },
  { value: "entity:active", label: "设定 · 启用" },
  { value: "entity:inactive", label: "设定 · 停用" },
  { value: "entity:unknown", label: "设定 · 未知" },
  { value: "relation:active", label: "关系 · 启用" },
  { value: "relation:ended", label: "关系 · 已结束" },
  { value: "relation:unknown", label: "关系 · 未知" },
  { value: "proposal:pending", label: "提案 · 待审核" },
  { value: "proposal:deferred", label: "提案 · 已延后" },
  { value: "proposal:stale", label: "提案 · 已过期" },
  { value: "proposal:accepted", label: "提案 · 已确认" },
  { value: "proposal:rejected", label: "提案 · 已忽略" },
  { value: "proposal:intentional", label: "提案 · 有意的矛盾" },
  { value: "proposal:reverted", label: "提案 · 已撤回" },
  { value: "summary:current", label: "摘要 · 现行" },
  { value: "summary:stale", label: "摘要 · 已过期" },
  { value: "summary:rejected", label: "摘要 · 已拒绝" },
  { value: "event:confirmed", label: "事件 · 已确认" },
  { value: "event:inferred", label: "事件 · 推断" },
  { value: "event:uncertain", label: "事件 · 不确定" },
];

const PROPOSAL_LABELS: Record<MemoryProposal["proposal_type"], string> = {
  entity_create: "新设定",
  entity_update: "更新设定",
  entity_state: "状态变化",
  story_event: "事件",
  chapter_summary: "章节摘要",
  entity_relation: "关系",
  foreshadowing: "线索伏笔",
  setting_supplement: "设定补充",
  potential_conflict: "潜在冲突",
};

type ReviewAction = "accept" | "edited" | "reject" | "defer" | "intentional" | "revert";

const CERTAINTY_LABELS: Record<Certainty, string> = {
  confirmed: "已确认",
  inferred: "推断",
  uncertain: "不确定",
};

const emptyDraft = (): EntityWrite => ({
  entity_type: "character",
  name: "",
  aliases: [],
  profile: { summary: "" },
  status: "active",
});

export function MemoryPanel({
  novelId,
  activeChapterId,
  activeRevision,
  activeTitle,
  editorDirty,
  chapters = [],
  materialVersion = 0,
}: MemoryPanelProps) {
  const [entities, setEntities] = useState<StoryEntity[]>([]);
  const [proposals, setProposals] = useState<MemoryProposal[]>([]);
  const [summaries, setSummaries] = useState<ChapterSummaryRecord[]>([]);
  const [events, setEvents] = useState<StoryEventRecord[]>([]);
  const [relations, setRelations] = useState<EntityRelation[]>([]);
  const [configs, setConfigs] = useState<ModelConfig[] | null>(null);
  const [draft, setDraft] = useState<EntityWrite>(emptyDraft());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [aliasText, setAliasText] = useState("");
  const [useMock, setUseMock] = useState(true);
  const [modelId, setModelId] = useState("");
  const [analyzing, setAnalyzing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [guidance, setGuidance] = useState(false);
  const [entityFilter, setEntityFilter] = useState("");
  const [chapterFilter, setChapterFilter] = useState("");
  const [storylineFilter, setStorylineFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [relationFrom, setRelationFrom] = useState("");
  const [relationTo, setRelationTo] = useState("");
  const [relationType, setRelationType] = useState("");
  const [relationTime, setRelationTime] = useState("");
  const [relationLine, setRelationLine] = useState("");
  const [relationEvidence, setRelationEvidence] = useState("");
  const [relationStatus, setRelationStatus] = useState<RelationStatus>("active");
  const [relationChapter, setRelationChapter] = useState("");
  const [stateEntityId, setStateEntityId] = useState("");
  const [stateChapterId, setStateChapterId] = useState("");
  const [stateSummary, setStateSummary] = useState("");
  const [stateEvidence, setStateEvidence] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [validUntil, setValidUntil] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      listEntities(novelId, controller.signal),
      listProposals(novelId, controller.signal),
      listChapterSummaries(novelId, controller.signal),
      listEvents(novelId, controller.signal),
      listRelations(novelId, controller.signal),
      listModelConfigs(controller.signal),
    ])
      .then(([nextEntities, nextProposals, nextSummaries, nextEvents, nextRelations, nextConfigs]) => {
        if (!active) {
          return;
        }
        setEntities(nextEntities);
        setProposals(nextProposals);
        setSummaries(nextSummaries);
        setEvents(nextEvents);
        setRelations(nextRelations);
        setConfigs(nextConfigs);
        setError("");
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "无法读取设定。");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [novelId, activeRevision, materialVersion]);

  const realModels = (configs ?? []).filter(
    (item) => item.is_enabled && item.provider_type === "openai_compatible",
  );
  const view = filterBible({
    entities,
    relations,
    events,
    summaries,
    proposals,
    entityFilter,
    chapterFilter,
    storyline: storylineFilter.trim(),
    statusFilter,
  });

  async function reload() {
    const [nextEntities, nextProposals, nextSummaries, nextEvents, nextRelations] = await Promise.all([
      listEntities(novelId),
      listProposals(novelId),
      listChapterSummaries(novelId),
      listEvents(novelId),
      listRelations(novelId),
    ]);
    setEntities(nextEntities);
    setProposals(nextProposals);
    setSummaries(nextSummaries);
    setEvents(nextEvents);
    setRelations(nextRelations);
  }

  async function runAnalyze(
    chapterId: string,
    revision: number,
    title: string,
    mock: boolean,
    scope: AnalysisScope = "full",
  ) {
    setError("");
    setGuidance(false);
    if (editorDirty && chapterId === activeChapterId) {
      setError("正文还有未保存的修改。请先保存，再分析。分析不会改写正文。");
      return;
    }
    if (scope === "full" && !mock && realModels.length === 0) {
      setGuidance(true);
      return;
    }
    setAnalyzing(true);
    setMessage(
      scope === "light"
        ? `正在对「${title}」的修订 ${revision} 做轻量检查…`
        : `正在分析「${title}」的修订 ${revision}…`,
    );
    try {
      const result = await analyzeChapter(chapterId, {
        revision,
        use_mock: scope === "light" ? false : mock,
        scope,
        ...(scope === "full" && !mock && modelId !== "" ? { model_config_id: modelId } : {}),
      });
      setMessage(result.message);
      await reload();
    } catch (cause: unknown) {
      setMessage("");
      setError(cause instanceof ApiError ? cause.message : "分析没有完成。正式设定没有改动。");
    } finally {
      setAnalyzing(false);
    }
  }

  useEffect(() => {
    registerMemoryAnalyze((request) => {
      const scope = request.scope ?? "full";
      void runAnalyze(
        request.chapterId,
        request.revision,
        request.title,
        scope === "full" ? useMock : false,
        scope,
      );
    });
    return () => {
      registerMemoryAnalyze(null);
    };
  });

  async function saveEntity() {
    const payload: EntityWrite = {
      ...draft,
      name: draft.name.trim(),
      aliases: aliasText
        .split(/[、,，]/)
        .map((item) => item.trim())
        .filter((item) => item !== ""),
    };
    setError("");
    try {
      if (editingId) {
        await updateEntity(editingId, payload);
        const impact = await materialImpact(novelId, "entity", editingId);
        setMessage(
          impact.affected.length > 0
            ? `已保存设定修改。有 ${impact.affected.length} 项资料可能受影响。`
            : "已保存设定修改。没有列出受影响的资料。",
        );
      } else {
        await createEntity(novelId, payload);
        setMessage("已新建设定。这不是分析提案。");
      }
      setDraft(emptyDraft());
      setAliasText("");
      setEditingId(null);
      await reload();
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "设定没有保存。");
    }
  }

  async function saveRelation() {
    setError("");
    try {
      await createRelation(novelId, {
        from_entity_id: relationFrom,
        to_entity_id: relationTo,
        relation_type: relationType.trim(),
        story_time_text: relationTime.trim() || null,
        storyline: relationLine.trim() || null,
        source_chapter_id: relationChapter || null,
        evidence_quote: relationEvidence.trim() || null,
        status: relationStatus,
      });
      setRelationType("");
      setRelationTime("");
      setRelationLine("");
      setRelationEvidence("");
      setMessage("已记录人物关系。故事时间可以留空。");
      await reload();
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "关系没有保存。");
    }
  }

  async function removeRelation(relationId: string) {
    if (!window.confirm("删除这条人物关系？正式正文不会改动。")) {
      return;
    }
    setBusyId(relationId);
    setError("");
    try {
      await deleteRelation(relationId);
      setMessage("已删除人物关系。");
      await reload();
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "关系没有删除。");
    } finally {
      setBusyId(null);
    }
  }

  async function saveState() {
    setError("");
    try {
      await createEntityState(stateEntityId, {
        chapter_id: stateChapterId,
        state_data: { summary: stateSummary.trim() },
        evidence_quote: stateEvidence.trim() || null,
        valid_from_text: validFrom.trim() || null,
        valid_until_text: validUntil.trim() || null,
      });
      setStateSummary("");
      setStateEvidence("");
      setValidFrom("");
      setValidUntil("");
      setMessage("已记录动态状态。有效时间留空也不会挡住写作。");
      await reload();
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "动态状态没有保存。");
    }
  }

  async function review(
    proposal: MemoryProposal,
    action: ReviewAction,
    edits?: Record<string, unknown>,
  ) {
    const writing = action === "accept" || action === "edited";
    if (writing && proposal.status === "stale") {
      const confirmed = window.confirm(
        "这份候选对应的章节修订已经过期。仍然确认并写入正式资料？正文不会被修改。",
      );
      if (!confirmed) {
        return;
      }
    }
    if (writing && (proposal.status === "pending" || proposal.status === "deferred")) {
      const confirmed = window.confirm(
        action === "edited"
          ? "按修改后的内容确认，并写入正式资料。正文不会被修改。"
          : "确认后会写入正式资料。正文不会被修改。",
      );
      if (!confirmed) {
        return;
      }
    }
    setBusyId(proposal.id);
    setError("");
    try {
      if (action === "accept") {
        await acceptProposal(proposal.id);
        setMessage("已确认。正式资料已更新。正文没有改动。");
      } else if (action === "edited") {
        await acceptProposal(proposal.id, edits);
        setMessage("已按修改确认。正式资料已更新。正文没有改动。");
      } else if (action === "reject") {
        await rejectProposal(proposal.id);
        setMessage("已忽略这条候选。正式资料没有改动。");
      } else if (action === "defer") {
        await deferProposal(proposal.id);
        setMessage("已延后。正式资料没有改动。");
      } else if (action === "intentional") {
        await markIntentionalProposal(proposal.id);
        setMessage("已标成有意安排的矛盾。正式设定没有被覆盖。");
      } else {
        await revertProposal(proposal.id);
        setMessage("已按字段撤回这条提案改过的设定。后来手改过的字段不会被整份覆盖。正文没有改动。");
      }
      await reload();
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "操作没有完成。");
    } finally {
      setBusyId(null);
    }
  }

  function beginEdit(entity: StoryEntity) {
    setEditingId(entity.id);
    setDraft({
      entity_type: entity.entity_type,
      name: entity.name,
      aliases: entity.aliases,
      profile: { summary: profileSummary(entity.profile) },
      status: entity.status,
    });
    setAliasText(entity.aliases.join("、"));
  }

  const chapterOptions = chapters.length
    ? chapters
    : activeChapterId
      ? [{ id: activeChapterId, title: activeTitle ?? "当前章节" }]
      : [];

  return (
    <section className="workspace-pane memory-pane" aria-labelledby="memory-heading">
      <h2 id="memory-heading">小说圣经</h2>
      <p className="hint">
        这里汇总正式设定、人物关系、动态状态、事件、摘要和待审核提案。分析只生成提案。接受之前，正式设定和正文都不会改。
      </p>
      {guidance ? (
        <p className="banner" role="status">
          还没有可用的模型。可以改用模拟分析，或先到模型设置填写服务信息。{" "}
          <a href="#/settings">打开模型设置</a>
        </p>
      ) : null}
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      {message ? (
        <p className="banner" role="status">
          {message}
        </p>
      ) : null}
      <div className="bible-filters">
        <label>
          实体
          <select
            aria-label="按实体筛选"
            value={entityFilter}
            onChange={(event) => {
              setEntityFilter(event.target.value);
            }}
          >
            <option value="">全部实体</option>
            {entities.map((entity) => (
              <option key={entity.id} value={entity.id}>
                {entity.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          章节
          <select
            aria-label="按章节筛选"
            value={chapterFilter}
            onChange={(event) => {
              setChapterFilter(event.target.value);
            }}
          >
            <option value="">全部章节</option>
            {chapterOptions.map((chapter) => (
              <option key={chapter.id} value={chapter.id}>
                {chapter.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          故事线
          <input
            aria-label="按故事线筛选"
            value={storylineFilter}
            placeholder="关系上的故事线标签"
            onChange={(event) => {
              setStorylineFilter(event.target.value);
            }}
          />
        </label>
        <label>
          状态
          <select
            aria-label="按状态筛选"
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
            }}
          >
            {STATUS_FILTERS.map((item) => (
              <option key={item.value || "all"} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {storylineFilter.trim() ? (
        <p className="hint">这里按人物关系上的故事线标签筛选，不读取大纲里的故事线，也不会因此藏起章节摘要和提案。</p>
      ) : null}
      <div className="memory-actions">
        <button
          className="primary"
          type="button"
          disabled={analyzing || !activeChapterId || activeRevision === null}
          onClick={() => {
            if (!activeChapterId || activeRevision === null) {
              return;
            }
            void runAnalyze(activeChapterId, activeRevision, activeTitle ?? "当前章节", useMock, "full");
          }}
        >
          {analyzing ? "正在分析…" : "分析当前章节"}
        </button>
        <button
          className="ghost"
          type="button"
          disabled={analyzing || !activeChapterId || activeRevision === null}
          onClick={() => {
            if (!activeChapterId || activeRevision === null) {
              return;
            }
            void runAnalyze(activeChapterId, activeRevision, activeTitle ?? "当前章节", false, "light");
          }}
        >
          轻量检查
        </button>
        <label className="check-row">
          <input
            type="checkbox"
            checked={useMock}
            onChange={(event) => {
              setUseMock(event.target.checked);
            }}
          />
          使用模拟分析
        </label>
        <label>
          本次模型
          <select
            aria-label="分析所用模型"
            value={modelId}
            disabled={useMock}
            onChange={(event) => {
              setModelId(event.target.value);
            }}
          >
            <option value="">使用默认模型</option>
            {realModels.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
                {item.is_default ? "（默认）" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      {useMock ? <p className="mock-badge">模拟分析</p> : null}
      {view.staleSummaries.length > 0 ? (
        <div className="stale-box">
          <h3>已过期摘要</h3>
          <p className="hint">这些摘要对应的章节修订已经变了，不能当作当前正文的事实。</p>
          <ul className="memory-list">
            {view.staleSummaries.map((item) => (
              <li key={item.id}>
                <span className="stale-badge">已过期</span>
                <strong>{item.chapter_title}</strong>
                <span className="hint">
                  来源修订 {item.source_revision}，当前修订 {item.chapter_revision}
                </span>
                <p>{item.summary}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <h3>提案与过期项</h3>
      {view.openProposals.length === 0 ? <p className="hint">没有待处理的提案。</p> : null}
      <ul className="memory-list">
        {view.openProposals.map((proposal) => (
          <li key={proposal.id} className="memory-card">
            <div className="memory-card-head">
              <strong>{PROPOSAL_LABELS[proposal.proposal_type]}</strong>
              <span className={proposal.certainty === "confirmed" ? "ok-badge" : "stale-badge"}>
                {CERTAINTY_LABELS[proposal.certainty]}
              </span>
              {proposal.status === "stale" ? <span className="stale-badge">修订已过期</span> : null}
              {proposal.status === "deferred" ? <span className="stale-badge">已延后</span> : null}
            </div>
            <p>{proposalTitle(proposal)}</p>
            <p className="hint">
              来源章节「{proposal.source_chapter_title}」修订 {proposal.source_revision}
            </p>
            {proposal.evidence_quote ? (
              <blockquote>证据：{proposal.evidence_quote}</blockquote>
            ) : (
              <p className="hint">没有可引用的原文证据，不会自动写入正式设定。</p>
            )}
            {proposal.evidence_in_source ? null : proposal.evidence_quote ? (
              <p className="hint">这段证据不在来源章节的原文里。</p>
            ) : null}
            <ProposalActions
              proposal={proposal}
              busy={busyId === proposal.id}
              onReview={(action, edits) => {
                void review(proposal, action, edits);
              }}
            />
          </li>
        ))}
      </ul>
      <details>
        <summary>已处理的提案</summary>
        <ul className="memory-list">
          {view.closedProposals.map((proposal) => (
            <li key={proposal.id}>
              <span>{PROPOSAL_LABELS[proposal.proposal_type]}</span>
              <span className="hint">
                {statusLabel(proposal.status)} · 「{proposal.source_chapter_title}」修订{" "}
                {proposal.source_revision}
              </span>
              {proposal.evidence_quote ? <blockquote>证据：{proposal.evidence_quote}</blockquote> : null}
              {proposal.status === "accepted" ? (
                <button
                  className="ghost"
                  type="button"
                  disabled={busyId === proposal.id}
                  onClick={() => {
                    void review(proposal, "revert");
                  }}
                >
                  撤回
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </details>
      <h3>实体档案</h3>
      <form
        className="memory-form"
        onSubmit={(event) => {
          event.preventDefault();
          void saveEntity();
        }}
      >
        <label>
          类型
          <select
            aria-label="设定类型"
            value={draft.entity_type}
            onChange={(event) => {
              setDraft({ ...draft, entity_type: event.target.value as EntityType });
            }}
          >
            {ENTITY_TYPES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          名称
          <input
            aria-label="设定名称"
            value={draft.name}
            onChange={(event) => {
              setDraft({ ...draft, name: event.target.value });
            }}
          />
        </label>
        <label>
          别名
          <input
            aria-label="设定别名"
            value={aliasText}
            placeholder="用顿号分隔"
            onChange={(event) => {
              setAliasText(event.target.value);
            }}
          />
        </label>
        <label>
          档案
          <textarea
            aria-label="设定档案"
            value={draft.profile.summary}
            onChange={(event) => {
              setDraft({ ...draft, profile: { summary: event.target.value } });
            }}
          />
        </label>
        <label>
          状态
          <select
            aria-label="设定状态"
            value={draft.status}
            onChange={(event) => {
              setDraft({ ...draft, status: event.target.value as EntityStatus });
            }}
          >
            {ENTITY_STATUS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <div className="inline-actions">
          <button className="primary" type="submit" disabled={draft.name.trim() === ""}>
            {editingId ? "保存修改" : "新建设定"}
          </button>
          {editingId ? (
            <button
              className="ghost"
              type="button"
              onClick={() => {
                setEditingId(null);
                setDraft(emptyDraft());
                setAliasText("");
              }}
            >
              取消编辑
            </button>
          ) : null}
        </div>
      </form>
      {view.entities.length === 0 ? <p className="hint">没有符合筛选的正式设定。</p> : null}
      <ul className="memory-list">
        {view.entities.map((entity) => (
          <li key={entity.id} className="memory-card">
            <div className="memory-card-head">
              <strong>{entity.name}</strong>
              <span className="hint">{typeLabel(entity.entity_type)}</span>
              <span className={entity.status === "active" ? "ok-badge" : "stale-badge"}>
                {entityStatusLabel(entity.status)}
              </span>
            </div>
            {profileSummary(entity.profile) ? <p>{profileSummary(entity.profile)}</p> : null}
            {entity.states.length === 0 ? <p className="hint">手工设定，还没有章节来源。</p> : null}
            {entity.states
              .filter((state) => chapterFilter === "" || state.chapter_id === chapterFilter)
              .map((state) => (
                <StateLine key={state.id} state={state} />
              ))}
            <button
              className="ghost"
              type="button"
              onClick={() => {
                beginEdit(entity);
              }}
            >
              编辑
            </button>
          </li>
        ))}
      </ul>
      <h3>人物关系</h3>
      <p className="hint">两端都必须是这本作品里的设定。故事时间和证据可以留空，留空不会挡住写作。</p>
      <form
        className="memory-form"
        onSubmit={(event) => {
          event.preventDefault();
          void saveRelation();
        }}
      >
        <label>
          从
          <select
            aria-label="关系起点"
            value={relationFrom}
            onChange={(event) => {
              setRelationFrom(event.target.value);
            }}
          >
            <option value="">选择设定</option>
            {entities.map((entity) => (
              <option key={entity.id} value={entity.id}>
                {entity.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          到
          <select
            aria-label="关系终点"
            value={relationTo}
            onChange={(event) => {
              setRelationTo(event.target.value);
            }}
          >
            <option value="">选择设定</option>
            {entities.map((entity) => (
              <option key={entity.id} value={entity.id}>
                {entity.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          关系类型
          <input
            aria-label="关系类型"
            value={relationType}
            onChange={(event) => {
              setRelationType(event.target.value);
            }}
          />
        </label>
        <label>
          故事时间
          <input
            aria-label="关系故事时间"
            value={relationTime}
            placeholder="可留空"
            onChange={(event) => {
              setRelationTime(event.target.value);
            }}
          />
        </label>
        <label>
          故事线标签
          <input
            aria-label="关系故事线"
            value={relationLine}
            placeholder="可留空，不是故事线表"
            onChange={(event) => {
              setRelationLine(event.target.value);
            }}
          />
        </label>
        <label>
          来源章节
          <select
            aria-label="关系来源章节"
            value={relationChapter}
            onChange={(event) => {
              setRelationChapter(event.target.value);
            }}
          >
            <option value="">暂不标注</option>
            {chapterOptions.map((chapter) => (
              <option key={chapter.id} value={chapter.id}>
                {chapter.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          证据
          <textarea
            aria-label="关系证据"
            value={relationEvidence}
            onChange={(event) => {
              setRelationEvidence(event.target.value);
            }}
          />
        </label>
        <label>
          关系状态
          <select
            aria-label="关系状态"
            value={relationStatus}
            onChange={(event) => {
              setRelationStatus(event.target.value as RelationStatus);
            }}
          >
            {RELATION_STATUS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <button
          className="primary"
          type="submit"
          disabled={relationFrom === "" || relationTo === "" || relationType.trim() === ""}
        >
          记录关系
        </button>
      </form>
      {view.relations.length === 0 ? <p className="hint">没有符合筛选的人物关系。</p> : null}
      <ul className="memory-list">
        {view.relations.map((relation) => (
          <li key={relation.id} className="memory-card">
            <div className="memory-card-head">
              <strong>
                {relation.from_entity_name} —{relation.relation_type}→ {relation.to_entity_name}
              </strong>
              <span className="hint">{relationStatusLabel(relation.status)}</span>
            </div>
            <p className="hint">
              {relation.storyline ? `故事线 ${relation.storyline} · ` : ""}
              {relation.story_time_text ? `故事时间 ${relation.story_time_text}` : "故事时间未填写"}
            </p>
            {relation.source_chapter_id ? (
              <p className="hint">
                来源章节「{relation.source_chapter_title ?? "未知章节"}」
                {relation.source_revision !== null ? `修订 ${relation.source_revision}` : ""}
              </p>
            ) : (
              <p className="hint">还没有来源章节。</p>
            )}
            {relation.evidence_quote ? (
              <blockquote>证据：{relation.evidence_quote}</blockquote>
            ) : (
              <p className="hint">证据未填写。</p>
            )}
            <button
              className="ghost"
              type="button"
              disabled={busyId === relation.id}
              onClick={() => {
                void removeRelation(relation.id);
              }}
            >
              删除关系
            </button>
          </li>
        ))}
      </ul>
      <h3>动态状态</h3>
      <p className="hint">有效时间可以留空。空着不会阻止记录状态，也不会阻止继续写正文。</p>
      <form
        className="memory-form"
        onSubmit={(event) => {
          event.preventDefault();
          void saveState();
        }}
      >
        <label>
          所属设定
          <select
            aria-label="状态所属设定"
            value={stateEntityId}
            onChange={(event) => {
              setStateEntityId(event.target.value);
            }}
          >
            <option value="">选择设定</option>
            {entities.map((entity) => (
              <option key={entity.id} value={entity.id}>
                {entity.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          来源章节
          <select
            aria-label="状态来源章节"
            value={stateChapterId}
            onChange={(event) => {
              setStateChapterId(event.target.value);
            }}
          >
            <option value="">选择章节</option>
            {chapterOptions.map((chapter) => (
              <option key={chapter.id} value={chapter.id}>
                {chapter.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          状态
          <input
            aria-label="动态状态内容"
            value={stateSummary}
            onChange={(event) => {
              setStateSummary(event.target.value);
            }}
          />
        </label>
        <label>
          生效起
          <input
            aria-label="有效时间起"
            value={validFrom}
            placeholder="可留空"
            onChange={(event) => {
              setValidFrom(event.target.value);
            }}
          />
        </label>
        <label>
          生效止
          <input
            aria-label="有效时间止"
            value={validUntil}
            placeholder="可留空"
            onChange={(event) => {
              setValidUntil(event.target.value);
            }}
          />
        </label>
        <label>
          证据
          <textarea
            aria-label="状态证据"
            value={stateEvidence}
            onChange={(event) => {
              setStateEvidence(event.target.value);
            }}
          />
        </label>
        <button
          className="primary"
          type="submit"
          disabled={stateEntityId === "" || stateChapterId === "" || stateSummary.trim() === ""}
        >
          记录状态
        </button>
      </form>
      {view.states.length === 0 ? <p className="hint">没有符合筛选的动态状态。</p> : null}
      <ul className="memory-list">
        {view.states.map((item) => (
          <li key={item.state.id} className="memory-card">
            <strong>{item.entityName}</strong>
            <StateLine state={item.state} />
          </li>
        ))}
      </ul>
      <h3>故事事件</h3>
      {view.events.length === 0 ? <p className="hint">没有符合筛选的事件。</p> : null}
      <ul className="memory-list">
        {view.events.map((event) => (
          <li key={event.id}>
            <p>{event.description}</p>
            <p className="hint">
              {CERTAINTY_LABELS[event.certainty]} · 「{event.chapter_title}」修订{" "}
              {event.source_revision ?? "未知"}
              {event.event_time_text ? ` · 故事时间 ${event.event_time_text}` : ""}
              {event.source_revision !== null && event.source_revision !== event.chapter_revision
                ? " · 来源修订已变化"
                : ""}
            </p>
            {event.evidence_quote ? <blockquote>证据：{event.evidence_quote}</blockquote> : null}
          </li>
        ))}
      </ul>
      <h3>章节摘要</h3>
      {view.livingSummaries.length === 0 ? <p className="hint">没有现行或已拒绝的摘要。</p> : null}
      <ul className="memory-list">
        {view.livingSummaries.map((item) => (
          <li key={item.id}>
            <div className="memory-card-head">
              <strong>{item.chapter_title}</strong>
              <span className={item.status === "current" ? "ok-badge" : "stale-badge"}>
                {item.status === "current" ? "现行" : "已拒绝"}
              </span>
            </div>
            <p>{item.summary}</p>
            <p className="hint">
              来源修订 {item.source_revision}，当前修订 {item.chapter_revision}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function StateLine({ state }: { state: EntityState }) {
  const summary = profileSummary(state.state_data);
  const validity =
    state.valid_from_text || state.valid_until_text
      ? `有效时间 ${state.valid_from_text ?? "未填"} 至 ${state.valid_until_text ?? "未填"}`
      : "有效时间未填写";
  return (
    <div>
      {summary ? <p>{summary}</p> : null}
      <p className="hint">
        来源章节「{state.chapter_title}」
        {state.source_revision !== null ? `修订 ${state.source_revision}` : ""} · {validity}
      </p>
      {state.evidence_quote ? <blockquote>证据：{state.evidence_quote}</blockquote> : null}
    </div>
  );
}

type BibleInput = {
  entities: StoryEntity[];
  relations: EntityRelation[];
  events: StoryEventRecord[];
  summaries: ChapterSummaryRecord[];
  proposals: MemoryProposal[];
  entityFilter: string;
  chapterFilter: string;
  storyline: string;
  statusFilter: string;
};

function filterBible(input: BibleInput) {
  const storylineIds = input.storyline
    ? new Set(
        input.relations
          .filter((relation) => containsText(relation.storyline, input.storyline))
          .flatMap((relation) => [relation.from_entity_id, relation.to_entity_id]),
      )
    : null;
  const entities = input.entities.filter((entity) => {
    if (input.entityFilter && entity.id !== input.entityFilter) {
      return false;
    }
    if (storylineIds && !storylineIds.has(entity.id)) {
      return false;
    }
    if (input.chapterFilter && !entityTouchesChapter(entity, input.relations, input.chapterFilter)) {
      return false;
    }
    if (input.statusFilter.startsWith("entity:") && entity.status !== input.statusFilter.slice(7)) {
      return false;
    }
    return true;
  });
  const visibleIds = new Set(entities.map((entity) => entity.id));
  const relations = input.relations.filter((relation) => {
    if (
      input.entityFilter &&
      relation.from_entity_id !== input.entityFilter &&
      relation.to_entity_id !== input.entityFilter
    ) {
      return false;
    }
    if (input.chapterFilter && relation.source_chapter_id !== input.chapterFilter) {
      return false;
    }
    if (input.storyline && !containsText(relation.storyline, input.storyline)) {
      return false;
    }
    if (
      input.statusFilter.startsWith("relation:") &&
      relation.status !== input.statusFilter.slice("relation:".length)
    ) {
      return false;
    }
    return true;
  });
  const states = entities.flatMap((entity) =>
    entity.states
      .filter((state) => input.chapterFilter === "" || state.chapter_id === input.chapterFilter)
      .map((state) => ({ entityName: entity.name, state })),
  );
  const events = input.events.filter((event) => {
    if (input.chapterFilter && event.chapter_id !== input.chapterFilter) {
      return false;
    }
    if (input.statusFilter.startsWith("event:") && event.certainty !== input.statusFilter.slice(6)) {
      return false;
    }
    if (input.entityFilter && !eventMentions(event, input.entities.filter((item) => item.id === input.entityFilter))) {
      return false;
    }
    if (storylineIds && !eventMentions(event, input.entities.filter((item) => storylineIds.has(item.id)))) {
      return false;
    }
    return true;
  });
  const summaries = input.summaries.filter((item) => {
    if (input.chapterFilter && item.chapter_id !== input.chapterFilter) {
      return false;
    }
    if (input.statusFilter.startsWith("summary:") && item.status !== input.statusFilter.slice(8)) {
      return false;
    }
    return true;
  });
  const proposals = input.proposals.filter((proposal) => {
    if (input.chapterFilter && proposal.source_chapter_id !== input.chapterFilter) {
      return false;
    }
    if (
      input.statusFilter.startsWith("proposal:") &&
      proposal.status !== input.statusFilter.slice("proposal:".length)
    ) {
      return false;
    }
    if (input.entityFilter) {
      const entity = input.entities.find((item) => item.id === input.entityFilter);
      const target = proposal.payload.target_entity_id;
      const name = proposal.payload.name;
      if (target === input.entityFilter) {
        return true;
      }
      if (entity && typeof name === "string" && name === entity.name) {
        return true;
      }
      return false;
    }
    return true;
  });
  return {
    entities,
    relations,
    states: input.entityFilter || storylineIds ? states.filter((item) => visibleIds.has(item.state.entity_id)) : states,
    events,
    staleSummaries: summaries.filter((item) => item.status === "stale"),
    livingSummaries: summaries.filter((item) => item.status !== "stale"),
    openProposals: proposals.filter(
      (item) => item.status === "pending" || item.status === "stale" || item.status === "deferred",
    ),
    closedProposals: proposals.filter(
      (item) => item.status !== "pending" && item.status !== "stale" && item.status !== "deferred",
    ),
  };
}

function entityTouchesChapter(entity: StoryEntity, relations: EntityRelation[], chapterId: string): boolean {
  if (entity.states.some((state) => state.chapter_id === chapterId)) {
    return true;
  }
  return relations.some(
    (relation) =>
      relation.source_chapter_id === chapterId &&
      (relation.from_entity_id === entity.id || relation.to_entity_id === entity.id),
  );
}

function eventMentions(event: StoryEventRecord, entities: StoryEntity[]): boolean {
  if (entities.length === 0) {
    return false;
  }
  const blob = `${event.description}\n${event.participants.join("\n")}`;
  return entities.some((entity) =>
    [entity.name, ...entity.aliases].some((name) => name !== "" && blob.includes(name)),
  );
}

function containsText(value: string | null, needle: string): boolean {
  return (value ?? "").toLocaleLowerCase().includes(needle.toLocaleLowerCase());
}

function proposalTitle(proposal: MemoryProposal): string {
  const name = proposal.payload.name;
  const summary = proposal.payload.summary;
  const description = proposal.payload.description;
  if (typeof name === "string" && name.trim()) {
    return name;
  }
  if (typeof summary === "string" && summary.trim()) {
    return summary;
  }
  if (typeof description === "string" && description.trim()) {
    return description;
  }
  const relation = proposal.payload.relation_type;
  const supplement = proposal.payload.supplement;
  if (typeof relation === "string" && relation.trim()) {
    return relation;
  }
  if (typeof supplement === "string" && supplement.trim()) {
    return supplement;
  }
  return "未命名提案";
}

function ProposalActions({
  proposal,
  busy,
  onReview,
}: {
  proposal: MemoryProposal;
  busy: boolean;
  onReview: (action: ReviewAction, edits?: Record<string, unknown>) => void;
}) {
  const key = editKey(proposal.proposal_type);
  const [text, setText] = useState(editableText(proposal));
  const [eventTime, setEventTime] = useState(payloadText(proposal, "event_time_text"));
  const [discovered, setDiscovered] = useState(payloadText(proposal, "character_discovered_text"));
  const [revealed, setRevealed] = useState(payloadText(proposal, "reader_revealed_text"));

  function edits(): Record<string, unknown> | undefined {
    const next: Record<string, unknown> = {};
    if (key === "state_data") {
      const current = proposal.payload.state_data;
      const base =
        current && typeof current === "object" ? { ...(current as Record<string, unknown>) } : {};
      next.state_data = { ...base, summary: text.trim() };
    } else if (key) {
      next[key] = text.trim();
    }
    if (proposal.proposal_type === "foreshadowing") {
      next.event_time_text = eventTime.trim() || null;
      next.character_discovered_text = discovered.trim() || null;
      next.reader_revealed_text = revealed.trim() || null;
    }
    return Object.keys(next).length > 0 ? next : undefined;
  }

  return (
    <>
      {key ? (
        <label>
          确认前可改
          <input
            aria-label={`修改候选 ${proposal.id}`}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
            }}
          />
        </label>
      ) : null}
      {proposal.proposal_type === "foreshadowing" ? (
        <>
          <label>
            事件实际发生时间
            <input
              aria-label={`事件时间 ${proposal.id}`}
              value={eventTime}
              onChange={(event) => {
                setEventTime(event.target.value);
              }}
            />
          </label>
          <label>
            角色发现时间
            <input
              aria-label={`发现时间 ${proposal.id}`}
              value={discovered}
              onChange={(event) => {
                setDiscovered(event.target.value);
              }}
            />
          </label>
          <label>
            向读者揭示时间
            <input
              aria-label={`揭示时间 ${proposal.id}`}
              value={revealed}
              onChange={(event) => {
                setRevealed(event.target.value);
              }}
            />
          </label>
        </>
      ) : null}
      <div className="inline-actions">
        <button
          className="primary"
          type="button"
          disabled={busy}
          onClick={() => {
            onReview("accept");
          }}
        >
          确认
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy}
          onClick={() => {
            onReview("edited", edits());
          }}
        >
          修改后确认
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy}
          onClick={() => {
            onReview("reject");
          }}
        >
          忽略
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy}
          onClick={() => {
            onReview("defer");
          }}
        >
          延后
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy}
          onClick={() => {
            onReview("intentional");
          }}
        >
          有意的矛盾
        </button>
      </div>
    </>
  );
}

function editKey(type: ProposalType): string | null {
  if (type === "entity_create" || type === "entity_update") {
    return "name";
  }
  if (type === "chapter_summary") {
    return "summary";
  }
  if (type === "entity_relation") {
    return "relation_type";
  }
  if (type === "setting_supplement") {
    return "supplement";
  }
  if (type === "entity_state") {
    return "state_data";
  }
  if (type === "story_event" || type === "foreshadowing" || type === "potential_conflict") {
    return "description";
  }
  return null;
}

function editableText(proposal: MemoryProposal): string {
  const key = editKey(proposal.proposal_type);
  if (key === "state_data") {
    const data = proposal.payload.state_data;
    if (data && typeof data === "object" && "summary" in data) {
      const summary = (data as { summary?: unknown }).summary;
      return typeof summary === "string" ? summary : "";
    }
    return "";
  }
  if (!key) {
    return "";
  }
  const value = proposal.payload[key];
  return typeof value === "string" ? value : "";
}

function payloadText(proposal: MemoryProposal, key: string): string {
  const value = proposal.payload[key];
  return typeof value === "string" ? value : "";
}

function profileSummary(profile: Record<string, unknown>): string {
  const summary = profile.summary;
  return typeof summary === "string" ? summary : "";
}

function typeLabel(value: EntityType): string {
  return ENTITY_TYPES.find((item) => item.value === value)?.label ?? "其他";
}

function entityStatusLabel(status: EntityStatus): string {
  return ENTITY_STATUS.find((item) => item.value === status)?.label ?? "未知";
}

function relationStatusLabel(status: RelationStatus): string {
  return RELATION_STATUS.find((item) => item.value === status)?.label ?? "未知";
}

function statusLabel(status: MemoryProposal["status"]): string {
  if (status === "accepted") {
    return "已确认";
  }
  if (status === "rejected") {
    return "已忽略";
  }
  if (status === "reverted") {
    return "已撤回";
  }
  if (status === "stale") {
    return "已过期";
  }
  if (status === "deferred") {
    return "已延后";
  }
  if (status === "intentional") {
    return "有意的矛盾";
  }
  return "待审核";
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
