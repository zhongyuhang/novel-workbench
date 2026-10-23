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
import { confirmDialog } from "./ConfirmDialog.tsx";
import { ContextPreview } from "./ContextPreview.tsx";
import { idleCandidate, reduceCandidate, type CandidateState } from "../features/ai/candidateStream.ts";
import {
  compiledPromptText,
  excludeIdsForScope,
  localPromptPreview,
  scopeLabel,
  type ContextScope,
} from "../features/ai/contextScope.ts";
import { readSavedInstructions, saveInstructionText } from "../features/ai/savedInstructions.ts";
import { stateFromTask } from "../features/ai/taskRecovery.ts";

type AiPanelProps = {
  novelId: string | null;
  chapter: Chapter | null;
  savedRevision: number | null;
  selectionText: string;
  editorDirty: boolean;
  onAccepted: (chapter: Chapter) => void;
};

const VERBS: Array<{ value: AiTaskType; label: string; field: string; hint: string }> = [
  { value: "continue", label: "续写", field: "接着写什么", hint: "写给这一次续写的要求。可以留空。" },
  { value: "polish", label: "润色", field: "润色要求", hint: "说明要保留的语气。留空就按当前正文润色。" },
  { value: "rewrite", label: "改写", field: "改成什么样", hint: "先在正文里选中一段，再说明想改成什么样。" },
  { value: "expand", label: "扩写", field: "往哪里扩", hint: "说明要展开的情节、对话或感官。" },
];

const EXTRA_TASKS: Array<{ value: AiTaskType; label: string; field: string; hint: string }> = [
  { value: "shrink", label: "缩写", field: "缩写要求", hint: "说明要留下什么。" },
  { value: "proofread", label: "校对", field: "校对要求", hint: "说明要检查的问题。" },
];

const TASKS = [...VERBS, ...EXTRA_TASKS];

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
  const [contextScope, setContextScope] = useState<ContextScope>({ outline: false, characters: false });
  const [savedInstructions, setSavedInstructions] = useState<string[]>(readSavedInstructions);
  const [instructionNote, setInstructionNote] = useState("");

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

  const taskMeta = TASKS.find((item) => item.value === taskType) ?? VERBS[0];
  const taskLabel = taskMeta?.label ?? "续写";
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
      const pins = await resolvedPins();
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
        pinned_include: pins.pinned_include,
        pinned_exclude: pins.pinned_exclude,
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
      const confirmed = await confirmDialog("没有选区，替换会覆盖整章正文。确定？", {
        tone: "danger",
      });
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

  function compilePayload(include: string[], exclude: string[]) {
    const words = maxWords.trim() === "" ? undefined : Number(maxWords);
    return {
      novel_id: novelId ?? "",
      chapter_id: chapter?.id,
      task_type: taskType,
      instruction: instruction.trim(),
      selection_text: selectionText,
      target_revision: savedRevision ?? undefined,
      constraints: {
        max_words: words !== undefined && Number.isFinite(words) ? words : undefined,
        must_include: mustInclude.trim() || undefined,
        must_avoid: mustAvoid.trim() || undefined,
      },
      pinned_include: include,
      pinned_exclude: exclude,
    };
  }

  async function resolvedPins(): Promise<{
    pinned_include: string[];
    pinned_exclude: string[];
    compiled: CompiledContext | null;
  }> {
    const manual = { pinned_include: pinnedInclude, pinned_exclude: pinnedExclude, compiled: null };
    if (!novelId || !chapter || savedRevision === null) {
      return manual;
    }
    try {
      const probe = await compileContext(compilePayload(pinnedInclude, pinnedExclude));
      if (!probe?.items) {
        return manual;
      }
      const extra = excludeIdsForScope(probe.items, contextScope, pinnedInclude);
      if (extra.length === 0) {
        return { pinned_include: pinnedInclude, pinned_exclude: pinnedExclude, compiled: probe };
      }
      const exclude = [...pinnedExclude];
      for (const id of extra) {
        if (!exclude.includes(id)) {
          exclude.push(id);
        }
      }
      const next = await compileContext(compilePayload(pinnedInclude, exclude));
      return {
        pinned_include: pinnedInclude,
        pinned_exclude: exclude,
        compiled: next?.items ? next : probe,
      };
    } catch {
      return manual;
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
      const pins = await resolvedPins();
      if (pins.compiled) {
        setCompiled(pins.compiled);
        return;
      }
      setCompiled(await compileContext(compilePayload(pins.pinned_include, pins.pinned_exclude)));
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

  function chooseTask(next: AiTaskType) {
    setTaskType(next);
    setApplyMode(defaultApplyMode(next, selectionText));
    setCompiled(null);
  }

  const previewText = localPromptPreview({
    taskLabel,
    instruction,
    selection: selectionText,
    maxWords,
    mustInclude,
    mustAvoid,
    scopeLabel: scopeLabel(contextScope),
  });
  const chapterOnly = !contextScope.outline && !contextScope.characters;

  return (
    <aside className="workspace-pane ai-pane" aria-labelledby="ai-heading">
      <h2 id="ai-heading">写作辅助</h2>
      <p className="hint">生成结果只是候选。采纳前不会改写正文。采纳后会写入正文，并在后台更新这一章的摘要。</p>
      <div className="verb-chips" role="group" aria-label="写作动作">
        {VERBS.map((item) => (
          <button
            key={item.value}
            type="button"
            aria-pressed={taskType === item.value}
            aria-label={`选择${item.label}`}
            onClick={() => {
              chooseTask(item.value);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="context-chips" role="group" aria-label="本次上下文范围">
        <button
          type="button"
          aria-pressed={chapterOnly}
          onClick={() => {
            setContextScope({ outline: false, characters: false });
            setCompiled(null);
          }}
        >
          仅本章
        </button>
        <button
          type="button"
          aria-pressed={contextScope.outline}
          onClick={() => {
            setContextScope((current) => ({ ...current, outline: !current.outline }));
            setCompiled(null);
          }}
        >
          +大纲
        </button>
        <button
          type="button"
          aria-pressed={contextScope.characters}
          onClick={() => {
            setContextScope((current) => ({ ...current, characters: !current.characters }));
            setCompiled(null);
          }}
        >
          +角色设定
        </button>
      </div>
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
          {taskMeta?.field ?? "接着写什么"}
          <textarea
            value={instruction}
            maxLength={8000}
            aria-label={taskMeta?.field ?? "接着写什么"}
            placeholder={taskMeta?.hint}
            onChange={(event) => {
              setInstruction(event.target.value);
              setInstructionNote("");
            }}
          />
        </label>
        <p className="hint">{taskMeta?.hint}</p>
        <div className="inline-actions">
          <button
            className="ghost"
            type="button"
            disabled={instruction.trim() === ""}
            onClick={() => {
              setSavedInstructions(saveInstructionText(instruction));
              setInstructionNote("已存为我的指令。只保存在这台浏览器里。");
            }}
          >
            存为我的指令
          </button>
          {savedInstructions.length > 0 ? (
            <label className="saved-instruction">
              我的指令
              <select
                aria-label="我的指令"
                value=""
                onChange={(event) => {
                  setInstruction(event.target.value);
                  setInstructionNote("");
                }}
              >
                <option value="">选用已保存的指令</option>
                {savedInstructions.map((item) => (
                  <option key={item} value={item}>
                    {item.length > 36 ? `${item.slice(0, 36)}…` : item}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
        {instructionNote ? (
          <p className="hint" role="status">
            {instructionNote}
          </p>
        ) : null}
        {taskType === "rewrite" ? (
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
          </section>
        ) : null}
        <div className="inline-actions">
          {taskType === "rewrite" ? (
            <>
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
            </>
          ) : (
            <>
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
            </>
          )}
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
        <details className="more-settings">
          <summary>更多设置</summary>
          <div className="ai-form">
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
            <div className="verb-chips" role="group" aria-label="其他动作">
              {EXTRA_TASKS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  aria-pressed={taskType === item.value}
                  aria-label={`选择${item.label}`}
                  onClick={() => {
                    chooseTask(item.value);
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </details>
        <section className="prompt-preview" aria-label="Prompt 预览">
          <h3>将发送的内容</h3>
          <p className="hint">下面是这次会交给模型的指令。点「查看本次上下文」可按当前范围编译材料。</p>
          <pre className="prompt-preview-body">{compiled ? compiledPromptText(compiled) : previewText}</pre>
          <p className="hint">
            {compiled
              ? `已按当前范围编译：纳入 ${compiled.items.filter((item) => item.included).length} 条。上面是将送给模型的材料，下面可以逐条固定或排除。`
              : "还没编译。上面是这次的指令和范围；查看本次上下文后，这里换成将送给模型的材料。"}
          </p>
        </section>
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
      {candidate.status === "completed" && candidate.partial ? (
        <p className="banner" role="status">
          {candidate.errorMessage || "模型超时，下面是已生成的片段，可以采纳。"}
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
