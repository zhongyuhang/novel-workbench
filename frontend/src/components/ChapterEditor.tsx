import { useEffect, useRef, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  diffChapterVersions,
  getChapter,
  getChapterVersion,
  listChapterVersions,
  restoreChapter,
  saveChapter,
} from "../api/catalog.ts";
import {
  ApiError,
  type Chapter,
  type ChapterStatus,
  type ChapterVersion,
  type ChapterVersionDetail,
  type ChapterVersionDiff,
  type SaveKind,
} from "../api/types.ts";
import { documentToText, wordCount, toTiptapDoc } from "../editor/documentText.ts";
import { diffLines, type DiffHunk } from "../editor/textDiff.ts";
import type { ChapterDraftState, SavePhase } from "../editor/useChapterAutosave.ts";
import { useChapterAutosave } from "../editor/useChapterAutosave.ts";

type ChapterEditorProps = {
  chapter: Chapter;
  autosaveDelayMs?: number;
  onSaved: (chapter: Chapter) => void;
  onUnsavedChange: (unsaved: boolean) => void;
  onSelectionChange?: (text: string) => void;
  adoptedChapter?: Chapter | null;
};

const STATUSES: Array<{ value: ChapterStatus; label: string }> = [
  { value: "outline", label: "提纲" },
  { value: "draft", label: "草稿" },
  { value: "revised", label: "修订" },
  { value: "final", label: "定稿" },
];

const SOURCE_LABEL: Record<ChapterVersion["change_source"], string> = {
  manual: "手动保存",
  ai_accepted: "采纳候选",
  restore: "恢复",
  import: "导入",
};

const PHASE_LABEL: Record<SavePhase, string> = {
  idle: "已同步",
  dirty: "未保存",
  saving: "正在保存",
  saved: "已保存",
  error: "保存失败",
  conflict: "版本冲突",
};

export function ChapterEditor({
  chapter,
  autosaveDelayMs,
  onSaved,
  onUnsavedChange,
  onSelectionChange,
  adoptedChapter = null,
}: ChapterEditorProps) {
  const draftRef = useRef<ChapterDraftState>({
    content: chapter.content,
    title: chapter.title,
    status: chapter.status,
  });
  const baselineReady = useRef(false);
  const [title, setTitle] = useState(chapter.title);
  const [status, setStatus] = useState<ChapterStatus>(chapter.status);
  const [versions, setVersions] = useState<ChapterVersion[] | null>(null);
  const [versionsError, setVersionsError] = useState("");
  const [versionReload, setVersionReload] = useState(0);
  const [actionError, setActionError] = useState("");
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [serverCopy, setServerCopy] = useState<Chapter | null>(null);
  const [serverCopyError, setServerCopyError] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [preview, setPreview] = useState<ChapterVersionDetail | null>(null);
  const [versionDiff, setVersionDiff] = useState<ChapterVersionDiff | null>(null);
  const [diffError, setDiffError] = useState("");

  const autosave = useChapterAutosave({
    chapterId: chapter.id,
    initialRevision: chapter.revision,
    initialTitle: chapter.title,
    initialStatus: chapter.status,
    initialContent: chapter.content,
    delayMs: autosaveDelayMs,
    getDraft: () => draftRef.current,
    onSaved: (saved, kind: SaveKind) => {
      onSaved(saved);
      if (kind === "manual") {
        setVersionReload((current) => current + 1);
      }
    },
    onUnsavedChange,
  });
  const autosaveRef = useRef(autosave);
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;
  const adoptedKey = useRef("");

  const editor = useEditor({
    immediatelyRender: true,
    shouldRerenderOnTransaction: true,
    extensions: [
      StarterKit.configure({
        trailingNode: false,
        link: { openOnClick: false, autolink: false },
      }),
    ],
    content: chapter.content,
    editorProps: {
      attributes: {
        "aria-label": "正文",
        class: "tiptap",
      },
    },
    onSelectionUpdate: ({ editor: instance }) => {
      const { from, to } = instance.state.selection;
      const text = from === to ? "" : instance.state.doc.textBetween(from, to, "\n\n");
      onSelectionChangeRef.current?.(text);
    },
    onUpdate: ({ editor: instance }) => {
      if (!baselineReady.current) {
        return;
      }
      draftRef.current = {
        ...draftRef.current,
        content: toTiptapDoc(instance.getJSON()),
      };
      autosaveRef.current.touch();
    },
  });

  useEffect(() => {
    if (!editor || baselineReady.current) {
      return;
    }
    const normalized = toTiptapDoc(editor.getJSON());
    draftRef.current = { ...draftRef.current, content: normalized };
    autosaveRef.current.noteBaseline(normalized);
    baselineReady.current = true;
  }, [editor]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void autosaveRef.current.saveNow();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  useEffect(() => {
    if (!autosave.unsaved) {
      return;
    }
    const onLeave = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onLeave);
    return () => {
      window.removeEventListener("beforeunload", onLeave);
    };
  }, [autosave.unsaved]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    listChapterVersions(chapter.id, controller.signal)
      .then((rows) => {
        if (!active) {
          return;
        }
        setVersions(rows);
        setVersionsError("");
      })
      .catch((error: unknown) => {
        if (!active || isAbort(error)) {
          return;
        }
        setVersionsError(error instanceof ApiError ? error.message : "无法读取版本。");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [chapter.id, versionReload]);

  useEffect(() => {
    if (autosave.phase !== "conflict") {
      return;
    }
    const controller = new AbortController();
    let active = true;
    getChapter(chapter.id, controller.signal)
      .then((fresh) => {
        if (!active) {
          return;
        }
        setServerCopy(fresh);
        setServerCopyError("");
      })
      .catch((error: unknown) => {
        if (!active || isAbort(error)) {
          return;
        }
        setServerCopy(null);
        setServerCopyError(error instanceof ApiError ? error.message : "无法读取服务器正文。");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [autosave.phase, chapter.id]);

  useEffect(() => {
    if (!editor || !adoptedChapter || adoptedChapter.id !== chapter.id) {
      return;
    }
    const key = `${adoptedChapter.id}:${adoptedChapter.revision}`;
    if (adoptedKey.current === key) {
      return;
    }
    adoptedKey.current = key;
    void applyRemote(adoptedChapter, "已采纳候选，并留下版本快照。").then(() => {
      setVersionReload((current) => current + 1);
    });
  }, [adoptedChapter, chapter.id, editor]);

  async function applyRemote(next: Chapter, notice: string) {
    if (!editor) {
      return;
    }
    editor.commands.setContent(next.content, { emitUpdate: false });
    const normalized = toTiptapDoc(editor.getJSON());
    draftRef.current = { content: normalized, title: next.title, status: next.status };
    setTitle(next.title);
    setStatus(next.status);
    autosave.noteBaseline(normalized);
    autosave.adoptServer({ ...next, content: normalized }, notice);
    onSaved(next);
    setActionError("");
  }

  async function loadServerCopy() {
    if (
      autosave.unsaved &&
      !window.confirm("载入服务器正文会替换编辑器里尚未保存的内容。确定载入？")
    ) {
      return;
    }
    try {
      const fresh = await getChapter(chapter.id);
      await applyRemote(fresh, "已载入服务器上的正文。");
    } catch (error: unknown) {
      setActionError(error instanceof ApiError ? error.message : "无法载入服务器正文。");
    }
  }

  async function overwriteWithLocal() {
    setActionError("");
    try {
      const fresh = serverCopy ?? (await getChapter(chapter.id));
      const draft = draftRef.current;
      const titleText = draft.title.trim();
      if (titleText === "") {
        setActionError("标题不能为空。本地草稿仍留在编辑器里。");
        return;
      }
      const saved = await saveChapter(chapter.id, {
        revision: fresh.revision,
        content: draft.content,
        title: titleText,
        status: draft.status,
        content_format: "tiptap_json",
        save_kind: "manual",
      });
      await applyRemote(saved, "已用本地草稿手动保存，并留下版本快照。自动保存本身不产生快照。");
      setServerCopy(null);
      setVersionReload((current) => current + 1);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 409) {
        setActionError(`${error.message} 本地草稿仍留在编辑器里。`);
        setServerCopy(null);
        return;
      }
      setActionError(error instanceof ApiError ? error.message : "手动保存没有完成。");
    }
  }

  async function showVersion(version: ChapterVersion) {
    setActionError("");
    setDiffError("");
    try {
      const [detail, diff] = await Promise.all([
        getChapterVersion(chapter.id, version.id),
        diffChapterVersions(chapter.id, version.id, "current"),
      ]);
      setPreview(detail);
      setVersionDiff(diff);
    } catch (error: unknown) {
      setPreview(null);
      setVersionDiff(null);
      setDiffError(error instanceof ApiError ? error.message : "无法读取这个版本。");
    }
  }

  async function compareSelected() {
    if (selectedIds.length !== 2) {
      return;
    }
    const [left, right] = selectedIds;
    if (!left || !right) {
      return;
    }
    setDiffError("");
    setPreview(null);
    try {
      setVersionDiff(await diffChapterVersions(chapter.id, left, right));
    } catch (error: unknown) {
      setVersionDiff(null);
      setDiffError(error instanceof ApiError ? error.message : "无法比较这两个版本。");
    }
  }

  function toggleSelected(versionId: string) {
    setSelectedIds((current) => {
      if (current.includes(versionId)) {
        return current.filter((item) => item !== versionId);
      }
      return [...current, versionId].slice(-2);
    });
  }

  async function restore(version: ChapterVersion) {
    const unsavedNote = autosave.unsaved
      ? "编辑器里还有未保存的修改，恢复会替换这些内容。"
      : "";
    const confirmed = window.confirm(
      `${unsavedNote}恢复修订 ${version.revision} 会写入新的修订，当前已保存的正文和已有版本都会保留。确定恢复？`,
    );
    if (!confirmed) {
      return;
    }
    setRestoringId(version.id);
    setActionError("");
    try {
      const restored = await restoreChapter(chapter.id, {
        revision: autosave.revision,
        version_id: version.id,
      });
      await applyRemote(restored, "已恢复为新修订。旧版本仍保留。");
      setVersionReload((current) => current + 1);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 409) {
        setActionError(`${error.message} 编辑器里的正文没有被覆盖。`);
        return;
      }
      setActionError(error instanceof ApiError ? error.message : "恢复失败。");
    } finally {
      setRestoringId(null);
    }
  }

  const liveCount = editor ? wordCount(toTiptapDoc(editor.getJSON())) : wordCount(chapter.content);
  const failure = autosave.phase === "error" || autosave.phase === "conflict";

  return (
    <div className="editor-form">
      <div className="editor-meta">
        <label>
          章节标题
          <input
            value={title}
            maxLength={200}
            onChange={(event) => {
              const next = event.target.value;
              draftRef.current = { ...draftRef.current, title: next };
              setTitle(next);
              autosave.touch();
            }}
          />
        </label>
        <label>
          状态
          <select
            value={status}
            onChange={(event) => {
              const next = event.target.value as ChapterStatus;
              draftRef.current = { ...draftRef.current, status: next };
              setStatus(next);
              autosave.touch();
            }}
          >
            {STATUSES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <p className="hint" role="status">
          {PHASE_LABEL[autosave.phase]} · 修订号 {autosave.revision} · 字数 {liveCount}
        </p>
      </div>
      <div className="editor-toolbar" role="toolbar" aria-label="正文格式">
        <button
          type="button"
          className="ghost"
          aria-pressed={editor?.isActive("bold") ?? false}
          disabled={!editor}
          onClick={() => {
            editor?.chain().focus().toggleBold().run();
          }}
        >
          粗体
        </button>
        <button
          type="button"
          className="ghost"
          aria-pressed={editor?.isActive("italic") ?? false}
          disabled={!editor}
          onClick={() => {
            editor?.chain().focus().toggleItalic().run();
          }}
        >
          斜体
        </button>
        <button
          type="button"
          className="ghost"
          aria-pressed={editor?.isActive("heading", { level: 2 }) ?? false}
          disabled={!editor}
          onClick={() => {
            editor?.chain().focus().toggleHeading({ level: 2 }).run();
          }}
        >
          标题
        </button>
        <button
          type="button"
          className="ghost"
          aria-pressed={editor?.isActive("bulletList") ?? false}
          disabled={!editor}
          onClick={() => {
            editor?.chain().focus().toggleBulletList().run();
          }}
        >
          列表
        </button>
      </div>
      <div className="editor-body">
        <EditorContent editor={editor} />
      </div>
      <p className="hint">
        正文以 Tiptap JSON 保存。停笔后会自动保存当前正文；手动保存会留下可恢复的快照。自动保存失败时，编辑器里的文字会留下来。
      </p>
      {failure ? (
        <p className="banner banner-error" role="alert">
          {autosave.message}
        </p>
      ) : null}
      {!failure && autosave.message ? (
        <p className="banner" role="status">
          {autosave.message}
        </p>
      ) : null}
      {actionError ? (
        <p className="banner banner-error" role="alert">
          {actionError}
        </p>
      ) : null}
      <div className="editor-actions">
        <button
          className="primary"
          type="button"
          disabled={
            autosave.phase === "saving" ||
            autosave.phase === "conflict" ||
            title.trim() === "" ||
            restoringId !== null
          }
          onClick={() => {
            void autosave.saveNow();
          }}
        >
          保存正文
        </button>
        {autosave.phase === "error" ? (
          <button
            className="ghost"
            type="button"
            onClick={() => {
              void autosave.retry();
            }}
          >
            重试
          </button>
        ) : null}
        {autosave.phase === "conflict" ? (
          <>
            <button
              className="ghost"
              type="button"
              onClick={() => {
                void loadServerCopy();
              }}
            >
              载入服务器正文
            </button>
            <button
              className="ghost"
              type="button"
              onClick={() => {
                void overwriteWithLocal();
              }}
            >
              用本地草稿手动保存
            </button>
          </>
        ) : null}
      </div>
      {autosave.phase === "conflict" ? (
        <div className="rewrite-compare" aria-label="修订冲突比较">
          <div>
            <h3>本地草稿</h3>
            <p>{editor ? documentToText(toTiptapDoc(editor.getJSON())) : documentToText(chapter.content)}</p>
          </div>
          <div>
            <h3>服务器正文</h3>
            {serverCopyError ? <p className="banner banner-error">{serverCopyError}</p> : null}
            <p>{serverCopy ? documentToText(serverCopy.content) : "正在读取服务器正文"}</p>
          </div>
          {serverCopy && editor ? (
            <div className="diff-view">
              <DiffList
                hunks={diffLines(
                  documentToText(toTiptapDoc(editor.getJSON())),
                  documentToText(serverCopy.content),
                )}
              />
            </div>
          ) : null}
        </div>
      ) : null}
      <section className="version-panel" aria-labelledby="version-heading">
        <h2 id="version-heading">版本</h2>
        <p className="hint">
          恢复前可以预览全文和差异。确认恢复会生成新修订，不会删掉中间版本。手动保存、采纳、恢复和导入才会留下快照；自动保存只更新当前正文。
        </p>
        <div className="inline-actions">
          <button
            className="ghost"
            type="button"
            disabled={selectedIds.length !== 2}
            onClick={() => {
              void compareSelected();
            }}
          >
            查看所选版本的差异
          </button>
        </div>
        {diffError ? (
          <p className="banner banner-error" role="alert">
            {diffError}
          </p>
        ) : null}
        {preview ? (
          <div className="version-preview" aria-label="恢复预览">
            <h3>
              预览修订 {preview.revision} · {SOURCE_LABEL[preview.change_source]} ·{" "}
              {formatTime(preview.created_at)}
            </h3>
            <p className="hint">{originLabel(preview)}</p>
            {preview.memory_proposal_ids.length > 0 ? (
              <p className="hint">记忆分析提案：{preview.memory_proposal_ids.join("、")}</p>
            ) : (
              <p className="hint">这一修订还没有关联的记忆分析提案。</p>
            )}
            <p className="candidate-box">{preview.text || "（空正文）"}</p>
          </div>
        ) : null}
        {versionDiff ? <VersionDiffView diff={versionDiff} /> : null}
        {versionsError ? (
          <p className="banner banner-error" role="alert">
            {versionsError}
          </p>
        ) : null}
        {versions === null && !versionsError ? <p role="status">正在读取版本</p> : null}
        {versions?.length === 0 ? (
          <p className="hint">还没有版本快照。手动保存会留下可恢复的快照；自动保存只更新当前正文。</p>
        ) : null}
        <ul className="version-list">
          {versions?.map((version) => (
            <li key={version.id}>
              <div>
                <p>
                  修订 {version.revision} · {SOURCE_LABEL[version.change_source]} · {version.word_count} 字
                </p>
                <p className="hint">{formatTime(version.created_at)}</p>
                <p className="hint">{originLabel(version)}</p>
                {version.change_note ? <p className="hint">{version.change_note}</p> : null}
                {version.preview ? <p>{version.preview}</p> : null}
                <label className="hint">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(version.id)}
                    onChange={() => {
                      toggleSelected(version.id);
                    }}
                  />
                  用来比较
                </label>
              </div>
              <div className="inline-actions">
                <button
                  className="ghost"
                  type="button"
                  aria-label={`预览修订 ${version.revision}`}
                  onClick={() => {
                    void showVersion(version);
                  }}
                >
                  预览
                </button>
                <button
                  className="ghost"
                  type="button"
                  aria-label={`恢复修订 ${version.revision}`}
                  disabled={restoringId !== null || autosave.phase === "saving"}
                  onClick={() => {
                    void restore(version);
                  }}
                >
                  恢复
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function originLabel(version: {
  change_source: ChapterVersion["change_source"];
  ai_task_id?: string | null;
  repair_candidate_id?: string | null;
}): string {
  if (version.ai_task_id) {
    return `来源：AI 任务 ${version.ai_task_id}`;
  }
  if (version.repair_candidate_id) {
    return `来源：质量修复建议 ${version.repair_candidate_id}`;
  }
  if (version.change_source === "manual") {
    return "来源：手动保存。自动保存不会单独留下这一条。";
  }
  if (version.change_source === "restore") {
    return "来源：从旧版本恢复。这次恢复本身是新修订。";
  }
  if (version.change_source === "import") {
    return "来源：导入。作品包导入尚未实现，整库备份会带上已有版本。";
  }
  return "来源：采纳后的正文修订。";
}

function VersionDiffView({ diff }: { diff: ChapterVersionDiff }) {
  return (
    <div className="version-preview" aria-label="版本差异">
      <h3>
        {diff.left.label} 与 {diff.right.label}
      </h3>
      <p className="hint">
        {formatTime(diff.left.created_at)} → {formatTime(diff.right.created_at)}
        {diff.left.change_source ? ` · ${SOURCE_LABEL[diff.left.change_source]}` : ""}
        {diff.right.change_source ? ` → ${SOURCE_LABEL[diff.right.change_source]}` : ""}
      </p>
      <DiffList hunks={diff.hunks} />
    </div>
  );
}

function DiffList({ hunks }: { hunks: DiffHunk[] }) {
  if (hunks.length === 0) {
    return <p className="hint">两边正文相同。</p>;
  }
  return (
    <div className="diff-view">
      {hunks.map((hunk, index) => (
        <p key={`${hunk.op}-${index}`} className={`diff-line diff-${hunk.op}`}>
          {hunk.text}
        </p>
      ))}
    </div>
  );
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
