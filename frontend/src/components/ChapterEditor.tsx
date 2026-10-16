import { useEffect, useRef, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  getChapter,
  listChapterVersions,
  restoreChapter,
} from "../api/catalog.ts";
import {
  ApiError,
  type Chapter,
  type ChapterStatus,
  type ChapterVersion,
  type SaveKind,
} from "../api/types.ts";
import { wordCount, toTiptapDoc } from "../editor/documentText.ts";
import type { ChapterDraftState, SavePhase } from "../editor/useChapterAutosave.ts";
import { useChapterAutosave } from "../editor/useChapterAutosave.ts";

type ChapterEditorProps = {
  chapter: Chapter;
  autosaveDelayMs?: number;
  onSaved: (chapter: Chapter) => void;
  onUnsavedChange: (unsaved: boolean) => void;
};

const STATUSES: Array<{ value: ChapterStatus; label: string }> = [
  { value: "outline", label: "大纲" },
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
          <button
            className="ghost"
            type="button"
            onClick={() => {
              void loadServerCopy();
            }}
          >
            载入服务器正文
          </button>
        ) : null}
      </div>
      <section className="version-panel" aria-labelledby="version-heading">
        <h2 id="version-heading">版本</h2>
        <p className="hint">恢复前会再确认一次。恢复会生成新修订，不会删掉旧版本。</p>
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
                {version.change_note ? <p className="hint">{version.change_note}</p> : null}
                {version.preview ? <p>{version.preview}</p> : null}
              </div>
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
            </li>
          ))}
        </ul>
      </section>
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
