import { useEffect, useState } from "react";
import { listModelConfigs } from "../api/models.ts";
import {
  acceptProposal,
  analyzeChapter,
  createEntity,
  listChapterSummaries,
  listEntities,
  listEvents,
  listProposals,
  rejectProposal,
  revertProposal,
  updateEntity,
  type Certainty,
  type ChapterSummaryRecord,
  type EntityStatus,
  type EntityType,
  type EntityWrite,
  type MemoryProposal,
  type StoryEntity,
  type StoryEventRecord,
} from "../api/memory.ts";
import { ApiError, type ModelConfig } from "../api/types.ts";
import { registerMemoryAnalyze } from "../features/memory/analyzeBridge.ts";

type MemoryPanelProps = {
  novelId: string;
  activeChapterId: string | null;
  activeRevision: number | null;
  activeTitle: string | null;
  editorDirty: boolean;
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

const PROPOSAL_LABELS: Record<MemoryProposal["proposal_type"], string> = {
  entity_create: "新设定",
  entity_update: "更新设定",
  entity_state: "状态变化",
  story_event: "事件",
  chapter_summary: "章节摘要",
};

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
}: MemoryPanelProps) {
  const [entities, setEntities] = useState<StoryEntity[]>([]);
  const [proposals, setProposals] = useState<MemoryProposal[]>([]);
  const [summaries, setSummaries] = useState<ChapterSummaryRecord[]>([]);
  const [events, setEvents] = useState<StoryEventRecord[]>([]);
  const [configs, setConfigs] = useState<ModelConfig[] | null>(null);
  const [draft, setDraft] = useState<EntityWrite>(emptyDraft());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [aliasText, setAliasText] = useState("");
  const [useMock, setUseMock] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [guidance, setGuidance] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      listEntities(novelId, controller.signal),
      listProposals(novelId, controller.signal),
      listChapterSummaries(novelId, controller.signal),
      listEvents(novelId, controller.signal),
      listModelConfigs(controller.signal),
    ])
      .then(([nextEntities, nextProposals, nextSummaries, nextEvents, nextConfigs]) => {
        if (!active) {
          return;
        }
        setEntities(nextEntities);
        setProposals(nextProposals);
        setSummaries(nextSummaries);
        setEvents(nextEvents);
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
  }, [novelId, activeRevision]);

  const realModels = (configs ?? []).filter(
    (item) => item.is_enabled && item.provider_type === "openai_compatible",
  );
  const staleSummaries = summaries.filter((item) => item.status === "stale");
  const openProposals = proposals.filter((item) => item.status === "pending" || item.status === "stale");

  async function reload() {
    const [nextEntities, nextProposals, nextSummaries, nextEvents] = await Promise.all([
      listEntities(novelId),
      listProposals(novelId),
      listChapterSummaries(novelId),
      listEvents(novelId),
    ]);
    setEntities(nextEntities);
    setProposals(nextProposals);
    setSummaries(nextSummaries);
    setEvents(nextEvents);
  }

  async function runAnalyze(chapterId: string, revision: number, title: string, mock: boolean) {
    setError("");
    setGuidance(false);
    if (editorDirty && chapterId === activeChapterId) {
      setError("正文还有未保存的修改。请先保存，再分析。分析不会改写正文。");
      return;
    }
    if (!mock && realModels.length === 0) {
      setGuidance(true);
      return;
    }
    setAnalyzing(true);
    setMessage(`正在分析「${title}」的修订 ${revision}…`);
    try {
      const result = await analyzeChapter(chapterId, { revision, use_mock: mock });
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
      void runAnalyze(request.chapterId, request.revision, request.title, useMock);
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
        setMessage("已保存设定修改。");
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

  async function review(proposal: MemoryProposal, action: "accept" | "reject" | "revert") {
    if (action === "accept" && proposal.status === "stale") {
      const confirmed = window.confirm(
        "这份提案对应的章节修订已经过期。仍然接受并写入正式设定？正文不会被修改。",
      );
      if (!confirmed) {
        return;
      }
    }
    if (action === "accept" && proposal.status === "pending") {
      const confirmed = window.confirm("接受后会写入正式设定。正文不会被修改。");
      if (!confirmed) {
        return;
      }
    }
    setBusyId(proposal.id);
    setError("");
    try {
      if (action === "accept") {
        await acceptProposal(proposal.id);
        setMessage("已接受提案，正式设定已更新。正文没有改动。");
      } else if (action === "reject") {
        await rejectProposal(proposal.id);
        setMessage("已拒绝提案。正式设定没有改动。");
      } else {
        await revertProposal(proposal.id);
        setMessage("已撤回这条提案写过的设定。正文没有改动。");
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

  return (
    <section className="workspace-pane memory-pane" aria-labelledby="memory-heading">
      <h2 id="memory-heading">设定与记忆</h2>
      <p className="hint">分析只生成提案。接受之前，正式设定和正文都不会改。</p>
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
      <div className="memory-actions">
        <button
          className="primary"
          type="button"
          disabled={analyzing || !activeChapterId || activeRevision === null}
          onClick={() => {
            if (!activeChapterId || activeRevision === null) {
              return;
            }
            void runAnalyze(activeChapterId, activeRevision, activeTitle ?? "当前章节", useMock);
          }}
        >
          {analyzing ? "正在分析…" : "分析当前章节"}
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
      </div>
      {useMock ? <p className="mock-badge">模拟分析</p> : null}
      {staleSummaries.length > 0 ? (
        <div className="stale-box">
          <h3>已过期摘要</h3>
          <p className="hint">这些摘要对应的章节修订已经变了，不能当作当前正文的事实。</p>
          <ul className="memory-list">
            {staleSummaries.map((item) => (
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
      <h3>提案</h3>
      {openProposals.length === 0 ? <p className="hint">没有待处理的提案。</p> : null}
      <ul className="memory-list">
        {openProposals.map((proposal) => (
          <li key={proposal.id} className="memory-card">
            <div className="memory-card-head">
              <strong>{PROPOSAL_LABELS[proposal.proposal_type]}</strong>
              <span className={proposal.certainty === "confirmed" ? "ok-badge" : "stale-badge"}>
                {CERTAINTY_LABELS[proposal.certainty]}
              </span>
              {proposal.status === "stale" ? <span className="stale-badge">修订已过期</span> : null}
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
            <div className="inline-actions">
              <button
                className="primary"
                type="button"
                disabled={busyId === proposal.id}
                onClick={() => {
                  void review(proposal, "accept");
                }}
              >
                接受
              </button>
              <button
                className="ghost"
                type="button"
                disabled={busyId === proposal.id}
                onClick={() => {
                  void review(proposal, "reject");
                }}
              >
                拒绝
              </button>
            </div>
          </li>
        ))}
      </ul>
      <details>
        <summary>已处理的提案</summary>
        <ul className="memory-list">
          {proposals
            .filter((item) => item.status !== "pending" && item.status !== "stale")
            .map((proposal) => (
              <li key={proposal.id}>
                <span>{PROPOSAL_LABELS[proposal.proposal_type]}</span>
                <span className="hint">
                  {statusLabel(proposal.status)} · 「{proposal.source_chapter_title}」修订{" "}
                  {proposal.source_revision}
                </span>
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
      <h3>正式设定</h3>
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
      {entities.length === 0 ? <p className="hint">还没有正式设定。</p> : null}
      <ul className="memory-list">
        {entities.map((entity) => (
          <li key={entity.id} className="memory-card">
            <div className="memory-card-head">
              <strong>{entity.name}</strong>
              <span className="hint">{typeLabel(entity.entity_type)}</span>
            </div>
            {profileSummary(entity.profile) ? <p>{profileSummary(entity.profile)}</p> : null}
            {entity.states[0] ? (
              <p className="hint">
                来源章节「{entity.states[0].chapter_title}」
                {entity.states[0].source_revision !== null
                  ? `修订 ${entity.states[0].source_revision}`
                  : ""}
                {entity.states[0].evidence_quote ? ` · 证据：${entity.states[0].evidence_quote}` : ""}
              </p>
            ) : (
              <p className="hint">手工设定，还没有章节来源。</p>
            )}
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
      {events.length > 0 ? (
        <>
          <h3>已确认事件</h3>
          <ul className="memory-list">
            {events.map((event) => (
              <li key={event.id}>
                <p>{event.description}</p>
                <p className="hint">
                  {CERTAINTY_LABELS[event.certainty]} · 「{event.chapter_title}」修订{" "}
                  {event.source_revision ?? "未知"}
                  {event.source_revision !== null && event.source_revision !== event.chapter_revision
                    ? " · 来源修订已变化"
                    : ""}
                </p>
                {event.evidence_quote ? <blockquote>证据：{event.evidence_quote}</blockquote> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
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
  return "未命名提案";
}

function profileSummary(profile: Record<string, unknown>): string {
  const summary = profile.summary;
  return typeof summary === "string" ? summary : "";
}

function typeLabel(value: EntityType): string {
  return ENTITY_TYPES.find((item) => item.value === value)?.label ?? "其他";
}

function statusLabel(status: MemoryProposal["status"]): string {
  if (status === "accepted") {
    return "已接受";
  }
  if (status === "rejected") {
    return "已拒绝";
  }
  if (status === "reverted") {
    return "已撤回";
  }
  if (status === "stale") {
    return "已过期";
  }
  return "待审核";
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
