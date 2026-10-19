import { useEffect, useState } from "react";
import type { Chapter, ChapterSummary } from "../api/types.ts";
import { ApiError } from "../api/types.ts";
import {
  checkConflicts,
  createForeshadowing,
  getNovelStats,
  listForeshadowing,
  setWritingGoal,
  updateForeshadowing,
  type ConflictCheck,
  type Foreshadowing,
  type ForeshadowingStatus,
  type NovelStats,
} from "../api/quality.ts";
import { QualityIssuesSection } from "./QualityIssuesSection.tsx";

type QualityPanelProps = {
  novelId: string;
  chapters: ChapterSummary[];
  activeChapterId: string | null;
  refreshKey: string;
  onManuscriptUpdated?: (chapter: Chapter) => void;
};

const STATUSES: Array<{ value: ForeshadowingStatus; label: string }> = [
  { value: "open", label: "未回收" },
  { value: "planned", label: "计划回收" },
  { value: "resolved", label: "已回收" },
  { value: "abandoned", label: "已放弃" },
  { value: "uncertain", label: "不确定" },
];

const STATUS_LABEL = Object.fromEntries(STATUSES.map((item) => [item.value, item.label])) as Record<
  ForeshadowingStatus,
  string
>;

const CONFLICT_LABEL = {
  attribute_contradiction: "属性说法不一致",
  negated_fact: "否定了已确认事实",
} as const;

const SEVERITY_LABEL = {
  low: "低",
  medium: "中",
  high: "高",
} as const;

export function QualityPanel({
  novelId,
  chapters,
  activeChapterId,
  refreshKey,
  onManuscriptUpdated,
}: QualityPanelProps) {
  const [statusFilter, setStatusFilter] = useState<"" | ForeshadowingStatus>("");
  const [items, setItems] = useState<Foreshadowing[]>([]);
  const [stats, setStats] = useState<NovelStats | null>(null);
  const [check, setCheck] = useState<ConflictCheck | null>(null);
  const [description, setDescription] = useState("");
  const [introducedChoice, setIntroducedChoice] = useState<string | null>(null);
  const introducedId = introducedChoice ?? activeChapterId ?? "";
  const [draftStatus, setDraftStatus] = useState<ForeshadowingStatus>("open");
  const [quote, setQuote] = useState("");
  const [goal, setGoal] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    listForeshadowing(novelId, statusFilter || undefined, controller.signal)
      .then((rows) => {
        if (active) {
          setItems(rows);
          setError("");
        }
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setError(messageFrom(cause, "无法读取伏笔。"));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [novelId, statusFilter]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    getNovelStats(novelId, controller.signal)
      .then((next) => {
        if (!active) {
          return;
        }
        setStats(next);
        setGoal(next.target_words === null ? "" : String(next.target_words));
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setError(messageFrom(cause, "无法读取字数统计。"));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [novelId, refreshKey]);

  async function addForeshadowing() {
    if (!introducedId || description.trim() === "") {
      setError("先选择埋下伏笔的章节，并写一句说明。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await createForeshadowing(novelId, {
        introduced_chapter_id: introducedId,
        description: description.trim(),
        status: draftStatus,
        payoff_chapter_id: null,
        evidence_quote: quote.trim() || null,
      });
      setDescription("");
      setQuote("");
      setMessage("已记下伏笔。这不会改写正文。");
      setItems(await listForeshadowing(novelId, statusFilter || undefined));
    } catch (cause: unknown) {
      setError(messageFrom(cause, "伏笔没有保存。"));
    } finally {
      setBusy(false);
    }
  }

  async function saveGoal() {
    const target = Number(goal);
    if (!Number.isInteger(target) || target < 1) {
      setError("目标字数需要是大于 0 的整数。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = await setWritingGoal(novelId, target);
      setStats(next);
      setMessage("已保存字数目标。正文没有被修改。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "目标没有保存。"));
    } finally {
      setBusy(false);
    }
  }

  async function runCheck() {
    if (!activeChapterId) {
      setError("请先打开一章，再检查疑似冲突。");
      return;
    }
    setBusy(true);
    setError("");
    setCheck(null);
    try {
      const next = await checkConflicts(activeChapterId);
      setCheck(next);
      setMessage(next.message);
    } catch (cause: unknown) {
      setError(messageFrom(cause, "冲突检查没有完成。正文和正式记忆都没有改动。"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="workspace-pane quality-pane" aria-labelledby="quality-heading">
      <h2 id="quality-heading">创作质量</h2>
      <p className="hint">
        伏笔、疑似冲突、质量问题和字数都只是辅助。建议不会自动改稿，也不会写入正式记忆。
      </p>
      <QualityIssuesSection
        novelId={novelId}
        activeChapterId={activeChapterId}
        onManuscriptUpdated={onManuscriptUpdated}
      />
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

      <section aria-labelledby="stats-heading">
        <h3 id="stats-heading">字数统计</h3>
        {stats ? (
          <>
            <p>
              全本 {stats.total_word_count} 字 · {stats.chapter_count} 章
              {stats.target_words !== null ? ` · 目标 ${stats.target_words} 字` : ""}
            </p>
            <ul className="memory-list">
              {stats.chapters.map((chapter) => (
                <li key={chapter.chapter_id}>
                  {chapter.title} · {chapter.word_count} 字
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p role="status">正在统计字数</p>
        )}
        <div className="inline-actions">
          <label>
            目标字数
            <input
              aria-label="目标字数"
              inputMode="numeric"
              value={goal}
              onChange={(event) => {
                setGoal(event.target.value);
              }}
            />
          </label>
          <button className="ghost" type="button" disabled={busy} onClick={() => void saveGoal()}>
            保存目标
          </button>
        </div>
      </section>

      <section aria-labelledby="conflict-heading">
        <h3 id="conflict-heading">冲突提示</h3>
        <p className="hint">只列出疑似冲突，并带来源。人物状态变化本身不会被当成矛盾。</p>
        <button className="primary" type="button" disabled={busy || !activeChapterId} onClick={() => void runCheck()}>
          检查疑似冲突
        </button>
        {check && check.provider_mode === "mock" ? <p className="mock-badge">本地规则</p> : null}
        {check && check.conflicts.length === 0 ? <p>没有发现疑似冲突。</p> : null}
        <ul className="memory-list">
          {check?.conflicts.map((item) => (
            <li key={`${item.conflict_type}-${item.source_quote}-${item.manuscript_snippet}`} className="memory-card">
              <div className="memory-card-head">
                <strong>{CONFLICT_LABEL[item.conflict_type]}</strong>
                <span className="stale-badge">
                  {SEVERITY_LABEL[item.severity]} · 置信 {item.confidence}
                </span>
              </div>
              <p>正文片段：{item.manuscript_snippet}</p>
              <p>已确认事实：{item.confirmed_fact}</p>
              <p>
                来源章节：{item.source_chapter_title || "未知章节"}
              </p>
              <blockquote>{item.source_quote}</blockquote>
              <p>{item.suggested_action}</p>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="foreshadow-heading">
        <h3 id="foreshadow-heading">伏笔</h3>
        <label>
          状态筛选
          <select
            aria-label="伏笔状态"
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as "" | ForeshadowingStatus);
            }}
          >
            <option value="">全部</option>
            {STATUSES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <div className="memory-form">
          <label>
            埋下的章节
            <select
              aria-label="埋下的章节"
              value={introducedId}
              onChange={(event) => {
                setIntroducedChoice(event.target.value);
              }}
            >
              <option value="">选择章节</option>
              {chapters.map((chapter) => (
                <option key={chapter.id} value={chapter.id}>
                  {chapter.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            说明
            <textarea
              aria-label="伏笔说明"
              value={description}
              maxLength={4000}
              onChange={(event) => {
                setDescription(event.target.value);
              }}
            />
          </label>
          <label>
            新建状态
            <select
              aria-label="新建伏笔状态"
              value={draftStatus}
              onChange={(event) => {
                setDraftStatus(event.target.value as ForeshadowingStatus);
              }}
            >
              {STATUSES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            证据原文
            <input
              aria-label="伏笔证据"
              value={quote}
              maxLength={2000}
              onChange={(event) => {
                setQuote(event.target.value);
              }}
            />
          </label>
          <button className="primary" type="button" disabled={busy || chapters.length === 0} onClick={() => void addForeshadowing()}>
            记下伏笔
          </button>
        </div>
        {items.length === 0 ? <p>这一筛选项下还没有伏笔。</p> : null}
        <ul className="memory-list">
          {items.map((item) => (
            <ForeshadowingCard
              key={`${item.id}-${item.updated_at}`}
              item={item}
              chapters={chapters}
              busy={busy}
              onSave={async (patch) => {
                setBusy(true);
                setError("");
                try {
                  await updateForeshadowing(item.id, patch);
                  setMessage("已更新伏笔。正文没有被修改。");
                  setItems(await listForeshadowing(novelId, statusFilter || undefined));
                } catch (cause: unknown) {
                  setError(messageFrom(cause, "伏笔没有更新。"));
                } finally {
                  setBusy(false);
                }
              }}
            />
          ))}
        </ul>
      </section>
    </aside>
  );
}

function ForeshadowingCard({
  item,
  chapters,
  busy,
  onSave,
}: {
  item: Foreshadowing;
  chapters: ChapterSummary[];
  busy: boolean;
  onSave: (patch: {
    description: string;
    status: ForeshadowingStatus;
    payoff_chapter_id: string | null;
    evidence_quote: string | null;
  }) => Promise<void>;
}) {
  const [description, setDescription] = useState(item.description);
  const [status, setStatus] = useState<ForeshadowingStatus>(item.status);
  const [payoffId, setPayoffId] = useState(item.payoff_chapter_id ?? "");
  const [quote, setQuote] = useState(item.evidence_quote ?? "");
  const introduced = chapters.find((chapter) => chapter.id === item.introduced_chapter_id);

  return (
    <li className="memory-card">
      <div className="memory-card-head">
        <strong>{STATUS_LABEL[item.status]}</strong>
        <span className="hint">埋于 {introduced?.title ?? "未知章节"}</span>
      </div>
      <label>
        说明
        <textarea
          aria-label={`伏笔说明 ${item.id}`}
          value={description}
          maxLength={4000}
          onChange={(event) => {
            setDescription(event.target.value);
          }}
        />
      </label>
      <label>
        状态
        <select
          aria-label={`伏笔状态 ${item.id}`}
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as ForeshadowingStatus);
          }}
        >
          {STATUSES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        回收章节
        <select
          aria-label={`回收章节 ${item.id}`}
          value={payoffId}
          onChange={(event) => {
            setPayoffId(event.target.value);
          }}
        >
          <option value="">尚未指定</option>
          {chapters.map((chapter) => (
            <option key={chapter.id} value={chapter.id}>
              {chapter.title}
            </option>
          ))}
        </select>
      </label>
      <label>
        证据原文
        <input
          aria-label={`伏笔证据 ${item.id}`}
          value={quote}
          maxLength={2000}
          onChange={(event) => {
            setQuote(event.target.value);
          }}
        />
      </label>
      <button
        className="ghost"
        type="button"
        disabled={busy || description.trim() === ""}
        onClick={() => {
          void onSave({
            description: description.trim(),
            status,
            payoff_chapter_id: payoffId || null,
            evidence_quote: quote.trim() || null,
          });
        }}
      >
        保存伏笔
      </button>
    </li>
  );
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
