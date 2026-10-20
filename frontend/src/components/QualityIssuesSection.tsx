import { useEffect, useState } from "react";
import type { Chapter } from "../api/types.ts";
import { ApiError } from "../api/types.ts";
import {
  acceptRepair,
  generateRepairs,
  listQualityIssues,
  rejectRepair,
  runQualityCheck,
  updateQualityIssue,
  type IssueStatus,
  type IssueType,
  type QualityIssue,
  type RepairCandidate,
} from "../api/quality.ts";

type QualityIssuesSectionProps = {
  novelId: string;
  activeChapterId: string | null;
  modelConfigId?: string | null;
  onManuscriptUpdated?: (chapter: Chapter) => void;
};

const TYPE_LABEL: Record<IssueType, string> = {
  fact_continuity: "事实连续性",
  time_continuity: "时间连续性",
  character_continuity: "人物连续性",
  foreshadowing: "伏笔管理",
  outline_execution: "大纲执行",
  text_surface: "文本层面",
};

const STATUS_LABEL: Record<IssueStatus, string> = {
  pending: "待处理",
  confirmed: "已确认",
  ignored: "已忽略",
  fixed: "已修复",
  expired: "已过期",
};

const SEVERITY_LABEL = {
  low: "低",
  medium: "中",
  high: "高",
} as const;

export function QualityIssuesSection({
  novelId,
  activeChapterId,
  modelConfigId = null,
  onManuscriptUpdated,
}: QualityIssuesSectionProps) {
  const [issues, setIssues] = useState<QualityIssue[]>([]);
  const [useModel, setUseModel] = useState(false);
  const [includeClosed, setIncludeClosed] = useState(false);
  const [scopeChapter, setScopeChapter] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    listQualityIssues(
      novelId,
      {
        includeClosed,
        chapterId: scopeChapter && activeChapterId ? activeChapterId : undefined,
      },
      controller.signal,
    )
      .then((rows) => {
        if (active) {
          setIssues(rows);
        }
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setError(messageFrom(cause, "无法读取质量问题。"));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [novelId, includeClosed, scopeChapter, activeChapterId]);

  async function reload() {
    setIssues(
      await listQualityIssues(novelId, {
        includeClosed,
        chapterId: scopeChapter && activeChapterId ? activeChapterId : undefined,
      }),
    );
  }

  async function runCheck() {
    setBusy(true);
    setError("");
    try {
      const result = await runQualityCheck(novelId, {
        use_model: useModel,
        chapter_id: scopeChapter ? activeChapterId : null,
        ...(useModel && modelConfigId ? { model_config_id: modelConfigId } : {}),
      });
      setMessage(result.message);
      await reload();
    } catch (cause: unknown) {
      setError(messageFrom(cause, "质量检查没有完成。正文和正式记忆都没有改动。"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="issues-heading">
      <h3 id="issues-heading">质量问题</h3>
      <p className="hint">
        规则检查可以离线重复运行。模型检查要单独打开。这里只记录疑似问题和建议，采纳前可以看差异。
      </p>
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
      <label>
        <input
          type="checkbox"
          checked={useModel}
          onChange={(event) => {
            setUseModel(event.target.checked);
          }}
        />
        启用模型检查
      </label>
      <label>
        <input
          type="checkbox"
          checked={includeClosed}
          onChange={(event) => {
            setIncludeClosed(event.target.checked);
          }}
        />
        显示已修复、已忽略和已过期
      </label>
      <label>
        <input
          type="checkbox"
          checked={scopeChapter}
          disabled={!activeChapterId}
          onChange={(event) => {
            setScopeChapter(event.target.checked);
          }}
        />
        只检查当前章节
      </label>
      <button className="primary" type="button" disabled={busy} onClick={() => void runCheck()}>
        运行规则检查
      </button>
      {issues.length === 0 ? <p>这一筛选项下还没有质量问题。</p> : null}
      <ul className="memory-list">
        {issues.map((issue) => (
          <IssueCard
            key={`${issue.id}-${issue.updated_at}`}
            issue={issue}
            busy={busy}
            useModel={useModel}
            modelConfigId={modelConfigId}
            onMessage={setMessage}
            onError={setError}
            onBusy={setBusy}
            onChanged={async () => {
              await reload();
            }}
            onManuscriptUpdated={onManuscriptUpdated}
          />
        ))}
      </ul>
    </section>
  );
}

function IssueCard({
  issue,
  busy,
  useModel,
  modelConfigId,
  onMessage,
  onError,
  onBusy,
  onChanged,
  onManuscriptUpdated,
}: {
  issue: QualityIssue;
  busy: boolean;
  useModel: boolean;
  modelConfigId?: string | null;
  onMessage: (value: string) => void;
  onError: (value: string) => void;
  onBusy: (value: boolean) => void;
  onChanged: () => Promise<void>;
  onManuscriptUpdated?: (chapter: Chapter) => void;
}) {
  const [candidates, setCandidates] = useState(issue.candidates);
  const visible = candidates.filter((item) => item.status !== "rejected");

  async function mark(status: "pending" | "confirmed" | "ignored") {
    onBusy(true);
    onError("");
    try {
      await updateQualityIssue(issue.id, status);
      onMessage("已更新问题状态。正文没有被修改。");
      await onChanged();
    } catch (cause: unknown) {
      onError(messageFrom(cause, "问题状态没有更新。"));
    } finally {
      onBusy(false);
    }
  }

  async function suggest() {
    onBusy(true);
    onError("");
    try {
      const result =
        useModel && modelConfigId
          ? await generateRepairs(issue.id, useModel, modelConfigId)
          : await generateRepairs(issue.id, useModel);
      setCandidates(result.candidates);
      onMessage(result.message);
    } catch (cause: unknown) {
      onError(messageFrom(cause, "没有生成修复建议。正文和正式记忆都没有改动。"));
    } finally {
      onBusy(false);
    }
  }

  async function accept(candidate: RepairCandidate) {
    if (!candidate.applicable) {
      return;
    }
    if (!window.confirm("采纳后会写入新的正文版本。正式设定不会改。确定采纳？")) {
      return;
    }
    onBusy(true);
    onError("");
    try {
      const result = await acceptRepair(candidate.id, candidate.target_revision);
      onMessage(result.message);
      if (result.chapter) {
        onManuscriptUpdated?.(result.chapter);
      }
      await onChanged();
    } catch (cause: unknown) {
      onError(messageFrom(cause, "没有写入正文。请重新检查后再决定。"));
    } finally {
      onBusy(false);
    }
  }

  async function reject(candidate: RepairCandidate) {
    onBusy(true);
    onError("");
    try {
      const result = await rejectRepair(candidate.id);
      onMessage(result.message);
      setCandidates((current) => current.map((item) => (item.id === candidate.id ? result.candidate : item)));
    } catch (cause: unknown) {
      onError(messageFrom(cause, "没有放弃这条建议。"));
    } finally {
      onBusy(false);
    }
  }

  return (
    <li className="memory-card">
      <div className="memory-card-head">
        <strong>{TYPE_LABEL[issue.issue_type]}</strong>
        <span className="stale-badge">
          {STATUS_LABEL[issue.status]} · {SEVERITY_LABEL[issue.severity]} · 置信 {issue.confidence}
        </span>
      </div>
      <p>
        章节：{issue.chapter_title || "未知章节"}
        {issue.target_revision !== null ? ` · 修订 ${issue.target_revision}` : ""}
        {issue.recheck_count > 0 ? ` · 已复查 ${issue.recheck_count} 次` : ""}
      </p>
      {issue.evidence_status === "insufficient" ? <p className="mock-badge">证据不足</p> : null}
      {issue.manuscript_snippet ? <p>正文片段：{issue.manuscript_snippet}</p> : null}
      {issue.location_note ? <p>{issue.location_note}</p> : null}
      <p>
        规则 {issue.rule_id} · {issue.rule_version}
        {issue.analysis_version ? ` · 分析 ${issue.analysis_version}` : ""}
      </p>
      <ul>
        {issue.evidence.map((item, index) => (
          <li key={`${issue.id}-evidence-${index}`}>
            {item.label}
            {item.source_chapter_title ? ` · 来源章节：${item.source_chapter_title}` : ""}
            {item.quote ? <blockquote>{item.quote}</blockquote> : null}
          </li>
        ))}
      </ul>
      {issue.related_refs.length > 0 ? (
        <p>涉及：{issue.related_refs.map((item) => item.label).join("、")}</p>
      ) : null}
      <p>{issue.suggested_action}</p>
      <div className="inline-actions">
        <button className="ghost" type="button" disabled={busy} onClick={() => void mark("confirmed")}>
          标为已确认
        </button>
        <button className="ghost" type="button" disabled={busy} onClick={() => void mark("ignored")}>
          忽略
        </button>
        <button className="ghost" type="button" disabled={busy} onClick={() => void mark("pending")}>
          标为待处理
        </button>
        <button className="ghost" type="button" disabled={busy || issue.status === "expired"} onClick={() => void suggest()}>
          生成修复建议
        </button>
      </div>
      {visible.map((candidate) => (
        <div key={candidate.id} className="memory-card">
          <p>{candidate.applicable ? "可预览的候选" : "不能直接套用"} · {candidate.status}</p>
          <p>{candidate.rationale}</p>
          {candidate.diff_preview ? <pre className="quality-diff">{candidate.diff_preview}</pre> : <p>没有可显示的差异。</p>}
          <div className="inline-actions">
            <button
              className="primary"
              type="button"
              disabled={busy || !candidate.applicable || candidate.status !== "proposed"}
              onClick={() => void accept(candidate)}
            >
              采纳此建议
            </button>
            <button
              className="ghost"
              type="button"
              disabled={busy || candidate.status !== "proposed"}
              onClick={() => void reject(candidate)}
            >
              不采纳
            </button>
          </div>
        </div>
      ))}
    </li>
  );
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
