import { useEffect, useState } from "react";
import { acceptAiTask, cancelAiTask, createAiTask, rejectAiTask, streamAiTask } from "../api/ai.ts";
import { listModelConfigs } from "../api/models.ts";
import {
  ApiError,
  type AiTaskType,
  type ApplyMode,
  type Chapter,
  type ModelConfig,
} from "../api/types.ts";
import { idleCandidate, reduceCandidate, type CandidateState } from "../features/ai/candidateStream.ts";

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

  async function start(useMock: boolean) {
    setError("");
    setNotice("");
    if (!novelId || !chapter || savedRevision === null) {
      setError("请先打开一章。生成不会在没有章节时开始。");
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
    setBusy(true);
    setCandidate({
      ...idleCandidate,
      status: "running",
      providerMode: useMock || explicitMock ? "mock" : null,
    });
    setTaskId(null);
    try {
      const words = maxWords.trim() === "" ? undefined : Number(maxWords);
      const task = await createAiTask({
        novel_id: novelId,
        chapter_id: chapter.id,
        task_type: taskType,
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
      });
      setTaskId(task.id);
      setLockedRevision(savedRevision);
      setCandidate((current) =>
        reduceCandidate(
          { ...current, providerMode: task.provider_mode },
          { event: "task.started", data: { provider_mode: task.provider_mode, status: task.status } },
        ),
      );
      await streamAiTask(task.id, (event) => {
        setCandidate((current) => reduceCandidate(current, event));
      });
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
      setCandidate((current) => ({
        ...current,
        status: "failed",
        ignoreTokens: true,
        errorMessage: api?.message ?? "生成没有完成。正文没有被修改。",
      }));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!taskId) {
      return;
    }
    setCandidate((current) => reduceCandidate(current, { event: "task.cancelled", data: {} }));
    try {
      await cancelAiTask(taskId);
      setNotice("已取消。迟到的片段不会写入正文。");
    } catch (cause: unknown) {
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
      setTaskId(null);
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "放弃没有完成。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="workspace-pane ai-pane" aria-labelledby="ai-heading">
      <h2 id="ai-heading">写作辅助</h2>
      <p className="hint">生成结果只是候选。采纳前不会改写正文，也不会写入记忆。</p>
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
            <option value="">自动选择已启用的模型</option>
            {(configs ?? [])
              .filter((item) => item.is_enabled)
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.display_name}
                  {item.provider_type === "mock" ? "（模拟）" : ""}
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
        </div>
      </div>
      {candidate.providerMode === "mock" ? <p className="mock-badge">模拟输出</p> : null}
      <p className="candidate-box" aria-label="候选文本" aria-live="polite">
        {candidate.text || "候选会显示在这里。"}
      </p>
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
