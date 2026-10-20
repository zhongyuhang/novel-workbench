import { useEffect, useState } from "react";
import {
  acceptAiTask,
  cancelAiTask,
  compileContext,
  createAiTask,
  getAiTask,
  getTaskContext,
  rejectAiTask,
  streamAiTask,
} from "../api/ai.ts";
import { listModelConfigs } from "../api/models.ts";
import {
  ApiError,
  type AiTaskType,
  type ApplyMode,
  type Chapter,
  type CompiledContext,
  type ModelConfig,
} from "../api/types.ts";
import { ContextPreview } from "./ContextPreview.tsx";
import { idleCandidate, reduceCandidate, type CandidateState } from "../features/ai/candidateStream.ts";
import { stateFromTask } from "../features/ai/taskRecovery.ts";

type AiPanelProps = {
  novelId: string | null;
  chapter: Chapter | null;
  savedRevision: number | null;
  selectionText: string;
  editorDirty: boolean;
  onAccepted: (chapter: Chapter) => void;
};

const TASKS: Array<{ value: AiTaskType; label: string }> = [
  { value: "continue", label: "续写" },
  { value: "rewrite", label: "改写" },
  { value: "polish", label: "润色" },
  { value: "expand", label: "扩写" },
  { value: "shrink", label: "缩写" },
  { value: "proofread", label: "校对" },
];

const APPLY_MODES: Array<{ value: ApplyMode; label: string }> = [
  { value: "append", label: "追加到章末" },
  { value: "insert", label: "插入到选区后" },
  { value: "replace_selection", label: "替换选区" },
];

export function AiPanel({
  novelId,
  chapter,
  savedRevision,
  selectionText,
  editorDirty,
  onAccepted,
}: AiPanelProps) {
  const [configs, setConfigs] = useState<ModelConfig[] | null>(null);
  const [configError, setConfigError] = useState("");
  const [taskType, setTaskType] = useState<AiTaskType>("continue");
  const [modelId, setModelId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [maxWords, setMaxWords] = useState("");
  const [mustInclude, setMustInclude] = useState("");
  const [mustAvoid, setMustAvoid] = useState("");
  const [applyMode, setApplyMode] = useState<ApplyMode>("append");
  const [guidance, setGuidance] = useState(false);
  const [busy, setBusy] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [lockedRevision, setLockedRevision] = useState<number | null>(null);
  const [candidate, setCandidate] = useState<CandidateState>(idleCandidate);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [compareSelection, setCompareSelection] = useState<string | null>(null);
  const [compiled, setCompiled] = useState<CompiledContext | null>(null);
  const [contextError, setContextError] = useState("");
  const [pinnedInclude, setPinnedInclude] = useState<string[]>([]);
  const [pinnedExclude, setPinnedExclude] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    listModelConfigs(controller.signal)
      .then((rows) => {
        setConfigs(rows);
        setConfigError("");
      })
      .catch((cause: unknown) => {
        if (isAbort(cause)) {
          return;
        }
        setConfigs([]);
        setConfigError(cause instanceof ApiError ? cause.message : "无法读取模型配置。");
      });
    return () => {
      controller.abort();
    };
  }, []);

  const taskLabel = TASKS.find((item) => item.value === taskType)?.label ?? "续写";
  const realModels = (configs ?? []).filter(
    (item) => item.is_enabled && item.provider_type === "openai_compatible",
  );
  const selected = (configs ?? []).find((item) => item.id === modelId) ?? null;
  const streaming = candidate.status === "running" || busy;

  async function start(useMock: boolean, taskOverride?: AiTaskType) {
    const nextType = taskOverride ?? taskType;
    setError("");
    setNotice("");
    if (!novelId || !chapter || savedRevision === null) {
      setError("请先打开一章。生成不会在没有章节时开始。");
      return;
    }
    if (taskOverride === "rewrite" && selectionText.trim() === "") {
      setError("请先在正文里选中要改写的文字。");
      return;
    }
    if (editorDirty) {
      setError("正文还有未保存的修改。请先保存，再开始生成或采纳。");
      return;
    }
    const explicitMock = selected?.provider_type === "mock" && selected.is_enabled;
    if (!useMock && !explicitMock && realModels.length === 0) {
      setGuidance(true);
      return;
    }
    if (!useMock && selected && !selected.is_enabled) {
      setGuidance(true);
      return;
    }
    setGuidance(false);
    if (taskOverride === "rewrite") {
      setTaskType("rewrite");
      setApplyMode("replace_selection");
      setCompareSelection(selectionText.trim());
    } else {
      setCompareSelection(null);
    }
    setBusy(true);
    setCandidate({
      ...idleCandidate,
      status: "running",
      providerMode: useMock || explicitMock ? "mock" : null,
    });
    setTaskId(null);
    let activeTaskId: string | null = null;
    try {
      const words = maxWords.trim() === "" ? undefined : Number(maxWords);
      const task = await createAiTask({
        novel_id: novelId,
        chapter_id: chapter.id,
        task_type: nextType,
        instruction: instruction.trim(),
        selection_text: selectionText,
        target_revision: savedRevision,
        model_config_id: useMock ? undefined : modelId || undefined,
        use_mock: useMock,
        constraints: {
          max_words: words !== undefined && Number.isFinite(words) ? words : undefined,
          must_include: mustInclude.trim() || undefined,
          must_avoid: mustAvoid.trim() || undefined,
        },
        pinned_include: pinnedInclude,
        pinned_exclude: pinnedExclude,
      });
      activeTaskId = task.id;
      setTaskId(task.id);
      setLockedRevision(savedRevision);
      try {
        setCompiled(await getTaskContext(task.id));
        setContextError("");
      } catch (cause: unknown) {
        setContextError(cause instanceof ApiError ? cause.message : "无法读取这次任务的上下文。");
      }
      setCandidate((current) =>
        reduceCandidate(
          { ...current, providerMode: task.provider_mode },
          { event: "task.started", data: { provider_mode: task.provider_mode, status: task.status } },
        ),
      );
      await streamAiTask(task.id, (event) => {
        setCandidate((current) => reduceCandidate(current, event));
      });
      await reconcile(task.id);
    } catch (cause: unknown) {
      if (isAbort(cause)) {
        return;
      }
      const api = cause instanceof ApiError ? cause : null;
      if (api?.code === "MODEL_NOT_CONFIGURED") {
        setGuidance(true);
        setCandidate(idleCandidate);
        return;
      }
      if (activeTaskId) {
        const recovered = await reconcile(activeTaskId);
        if (recovered) {
          return;
        }
      }
      setCandidate((current) => ({
        ...current,
        status: "failed",
        ignoreTokens: true,
        disconnected: false,
        errorMessage: api?.message ?? "生成没有完成。正文没有被修改。",
      }));
    } finally {
      setBusy(false);
    }
  }

  async function reconcile(taskIdToRead: string): Promise<boolean> {
    try {
      const task = await getAiTask(taskIdToRead);
      setCandidate((current) => stateFromTask(current, task));
      if (task.status === "queued" || task.status === "running") {
        setNotice("连接中断。任务仍在服务器上，可以重新查看。正文没有被改写。");
      }
      return true;
    } catch (cause: unknown) {
      setCandidate((current) => {
        if (current.status === "completed" || current.status === "cancelled" || current.status === "failed") {
          return current;
        }
        return {
          ...current,
          disconnected: true,
          errorMessage: cause instanceof ApiError ? cause.message : "无法读取任务状态。",
        };
      });
      setNotice("连接中断。任务状态以服务器为准，可以重新查看。正文没有被改写。");
      return false;
    }
  }

  async function cancel() {
    if (!taskId) {
      return;
    }
    const cancellingId = taskId;
    setCandidate((current) => reduceCandidate(current, { event: "task.cancelled", data: {} }));
    try {
      await cancelAiTask(cancellingId);
      await reconcile(cancellingId);
      setNotice("已取消。迟到的片段不会写入正文。");
    } catch (cause: unknown) {
      try {
        const task = await getAiTask(cancellingId);
        if (task.status !== "cancelled") {
          setCandidate((current) =>
            stateFromTask(
              {
                ...current,
                status: "running",
                ignoreTokens: false,
                completedCount: 0,
                text: "",
              },
              task,
            ),
          );
        }
      } catch {
        setCandidate((current) => ({ ...current, disconnected: true }));
      }
      setError(cause instanceof ApiError ? cause.message : "取消没有完成。");
    }
  }

  async function accept() {
    if (!taskId || lockedRevision === null || candidate.status !== "completed") {
      return;
    }
    if (editorDirty) {
      setError("正文还有未保存的修改。请先保存，再采纳候选。");
      return;
    }
    if (applyMode === "replace_selection" && selectionText.trim() === "") {
      const confirmed = window.confirm("没有选区，替换会覆盖整章正文。确定？");
      if (!confirmed) {
        return;
      }
    }
    setError("");
    setBusy(true);
    try {
      const result = await acceptAiTask(taskId, {
        target_revision: lockedRevision,
        apply_mode: applyMode,
      });
      setNotice("已采纳候选，并留下版本快照。");
      setCandidate(idleCandidate);
      setCompareSelection(null);
      setTaskId(null);
      onAccepted(result.chapter);
    } catch (cause: unknown) {
      const api = cause instanceof ApiError ? cause : null;
      if (api?.status === 409) {
        setError(`${api.message} 正文没有被覆盖。`);
        return;
      }
      setError(api?.message ?? "采纳没有完成。正文没有被修改。");
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    if (!taskId || candidate.status !== "completed") {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await rejectAiTask(taskId);
      setNotice("已放弃候选。正文没有改动。");
      setCandidate(idleCandidate);
      setCompareSelection(null);
      setTaskId(null);
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "放弃没有完成。");
    } finally {
      setBusy(false);
    }
  }

  async function previewContext() {
    setContextError("");
    if (!novelId || !chapter || savedRevision === null) {
      setContextError("请先打开一章，再查看这次会用到的上下文。");
      return;
    }
    if (editorDirty) {
      setContextError("正文还有未保存的修改。请先保存，再编译上下文。");
      return;
    }
    setBusy(true);
    try {
      const words = maxWords.trim() === "" ? undefined : Number(maxWords);
      const next = await compileContext({
        novel_id: novelId,
        chapter_id: chapter.id,
        task_type: taskType,
        instruction: instruction.trim(),
        selection_text: selectionText,
        target_revision: savedRevision,
        constraints: {
          max_words: words !== undefined && Number.isFinite(words) ? words : undefined,
          must_include: mustInclude.trim() || undefined,
          must_avoid: mustAvoid.trim() || undefined,
        },
        pinned_include: pinnedInclude,
        pinned_exclude: pinnedExclude,
      });
      setCompiled(next);
    } catch (cause: unknown) {
      setCompiled(null);
      setContextError(cause instanceof ApiError ? cause.message : "上下文编译失败，没有开始生成。");
    } finally {
      setBusy(false);
    }
  }

  function togglePin(id: string, include: boolean) {
    if (include) {
      setPinnedInclude((current) =>
        current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
      );
      setPinnedExclude((current) => current.filter((item) => item !== id));
      return;
    }
    setPinnedExclude((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
    setPinnedInclude((current) => current.filter((item) => item !== id));
  }

  return (
    <aside className="workspace-pane ai-pane" aria-labelledby="ai-heading">
      <h2 id="ai-heading">写作辅助</h2>
      <p className="hint">生成结果只是候选。采纳前不会改写正文，也不会写入记忆。</p>
      <section className="selection-rewrite" aria-label="选区改写">
        <h3>选区改写</h3>
        <p className="hint">
          {selectionText.trim()
            ? "将只改写选中的文字。候选需要你比较后再采纳或放弃。"
            : "在正文里选中一段文字后，可以只改这一段。"}
        </p>
        {selectionText.trim() ? (
          <p className="candidate-box" aria-label="当前选区">
            {selectionText}
          </p>
        ) : null}
        <div className="inline-actions">
          <button
            className="primary"
            type="button"
            disabled={streaming || configs === null || selectionText.trim() === ""}
            onClick={() => {
              void start(false, "rewrite");
            }}
          >
            选区改写
          </button>
          <button
            className="ghost"
            type="button"
            disabled={streaming || configs === null || selectionText.trim() === ""}
            onClick={() => {
              void start(true, "rewrite");
            }}
          >
            用模拟模型改写选区
          </button>
        </div>
      </section>
      {configError ? (
        <p className="banner banner-error" role="alert">
          {configError}
        </p>
      ) : null}
      {guidance ? (
        <p className="banner" role="status">
          还没有可用的模型。请先到模型设置填写服务地址、模型名和密钥。这一步不会改写正文。{" "}
          <a href="#/settings">打开模型设置</a>
        </p>
      ) : null}
      <div className="ai-form">
        <label>
          任务
          <select
            aria-label="任务类型"
            value={taskType}
            onChange={(event) => {
              const next = event.target.value as AiTaskType;
              setTaskType(next);
              setApplyMode(defaultApplyMode(next, selectionText));
            }}
          >
            {TASKS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          模型
          <select
            aria-label="模型"
            value={modelId}
            onChange={(event) => {
              setModelId(event.target.value);
            }}
          >
            <option value="">
              {configs?.find((item) => item.is_default)
                ? `使用默认模型（${configs.find((item) => item.is_default)?.display_name ?? ""}）`
                : "使用默认模型"}
            </option>
            {(configs ?? [])
              .filter((item) => item.is_enabled)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.display_name}
                  {item.is_default ? "（默认）" : ""}
                  {item.provider_type === "mock" ? "（模拟）" : ""}
                  {item.last_test_status === "stale" ? "（需重测）" : ""}
                </option>
              ))}
          </select>
        </label>
        <label>
          补充要求
          <textarea
            value={instruction}
            maxLength={8000}
            onChange={(event) => {
              setInstruction(event.target.value);
            }}
          />
        </label>
        <label>
          最多字数
          <input
            inputMode="numeric"
            value={maxWords}
            onChange={(event) => {
              setMaxWords(event.target.value);
            }}
          />
        </label>
        <label>
          必须包含
          <input
            value={mustInclude}
            maxLength={2000}
            onChange={(event) => {
              setMustInclude(event.target.value);
            }}
          />
        </label>
        <label>
          不要出现
          <input
            value={mustAvoid}
            maxLength={2000}
            onChange={(event) => {
              setMustAvoid(event.target.value);
            }}
          />
        </label>
        <ContextPreview
          context={compiled}
          pinnedInclude={pinnedInclude}
          pinnedExclude={pinnedExclude}
          busy={streaming}
          error={contextError}
          onPreview={() => {
            void previewContext();
          }}
          onRecompile={() => {
            void previewContext();
          }}
          onToggleInclude={(id) => {
            togglePin(id, true);
          }}
          onToggleExclude={(id) => {
            togglePin(id, false);
          }}
        />
        <div className="inline-actions">
          <button
            className="primary"
            type="button"
            disabled={streaming || configs === null}
            onClick={() => {
              void start(false);
            }}
          >
            {taskLabel}
          </button>
          <button
            className="ghost"
            type="button"
            disabled={streaming || configs === null}
            onClick={() => {
              void start(true);
            }}
          >
            用模拟模型试运行
          </button>
          {candidate.status === "running" ? (
            <button
              className="ghost"
              type="button"
              onClick={() => {
                void cancel();
              }}
            >
              取消
            </button>
          ) : null}
          {candidate.disconnected && taskId ? (
            <button
              className="ghost"
              type="button"
              onClick={() => {
                void reconcile(taskId);
              }}
            >
              重新查看任务
            </button>
          ) : null}
        </div>
      </div>
      {candidate.providerMode === "mock" ? <p className="mock-badge">模拟输出</p> : null}
      {compareSelection && candidate.status === "completed" ? (
        <div className="rewrite-compare" aria-label="选区对比">
          <div>
            <h3>当前选区</h3>
            <p>{compareSelection}</p>
          </div>
          <div>
            <h3>改写候选</h3>
            <p>{candidate.text || "（空）"}</p>
          </div>
        </div>
      ) : null}
      <p className="candidate-box" aria-label="候选文本" aria-live="polite">
        {candidate.text || "候选会显示在这里。"}
      </p>
      {candidate.disconnected ? (
        <p className="banner" role="status">
          进度连接中断了。上面的文字只是已经收到的片段，最终候选以服务器上的任务为准。
        </p>
      ) : null}
      {candidate.status === "failed" ? (
        <p className="banner banner-error" role="alert">
          {candidate.errorMessage}
        </p>
      ) : null}
      {candidate.status === "cancelled" ? (
        <p className="banner" role="status">
          已取消。正文没有被改写。
        </p>
      ) : null}
      {candidate.status === "completed" ? (
        <div className="ai-form">
          <label>
            采纳方式
            <select
              aria-label="采纳方式"
              value={applyMode}
              onChange={(event) => {
                setApplyMode(event.target.value as ApplyMode);
              }}
            >
              {APPLY_MODES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <div className="inline-actions">
            <button
              className="primary"
              type="button"
              disabled={busy}
              onClick={() => {
                void accept();
              }}
            >
              采纳
            </button>
            <button
              className="ghost"
              type="button"
              disabled={busy}
              onClick={() => {
                void reject();
              }}
            >
              放弃
            </button>
          </div>
        </div>
      ) : null}
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="banner" role="status">
          {notice}
        </p>
      ) : null}
    </aside>
  );
}

function defaultApplyMode(taskType: AiTaskType, selectionText: string): ApplyMode {
  if (taskType === "continue" || selectionText.trim() === "") {
    return "append";
  }
  return "replace_selection";
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
