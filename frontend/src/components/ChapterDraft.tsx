import { useState, type FormEvent } from "react";
import { getChapter, saveChapter } from "../api/catalog.ts";
import { ApiError, type Chapter, type ChapterStatus } from "../api/types.ts";
import { CANONICAL_CONTENT_FORMAT } from "../editor/contentFormat.ts";
import { documentToText, textToDocument } from "../editor/documentText.ts";

type ChapterDraftProps = {
  chapter: Chapter;
  onSaved: (chapter: Chapter) => void;
};

const STATUSES: Array<{ value: ChapterStatus; label: string }> = [
  { value: "outline", label: "大纲" },
  { value: "draft", label: "草稿" },
  { value: "revised", label: "修订" },
  { value: "final", label: "定稿" },
];

export function ChapterDraft({ chapter, onSaved }: ChapterDraftProps) {
  const [title, setTitle] = useState(chapter.title);
  const [status, setStatus] = useState<ChapterStatus>(chapter.status);
  const [draft, setDraft] = useState(() => documentToText(chapter.content));
  const [revision, setRevision] = useState(chapter.revision);
  const [wordCount, setWordCount] = useState(chapter.word_count);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState("");

  const document = textToDocument(draft);

  async function loadServerCopy() {
    setPending(true);
    try {
      const fresh = await getChapter(chapter.id);
      setTitle(fresh.title);
      setStatus(fresh.status);
      setDraft(documentToText(fresh.content));
      setRevision(fresh.revision);
      setWordCount(fresh.word_count);
      setConflict("");
      setNotice("已载入服务器上的正文。");
      onSaved(fresh);
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : "无法载入服务器正文。";
      setNotice(message);
    } finally {
      setPending(false);
    }
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setNotice("");
    try {
      const saved = await saveChapter(chapter.id, {
        revision,
        title: title.trim(),
        status,
        content: document,
        content_format: CANONICAL_CONTENT_FORMAT,
      });
      setRevision(saved.revision);
      setWordCount(saved.word_count);
      setTitle(saved.title);
      setStatus(saved.status);
      setDraft(documentToText(saved.content));
      setConflict("");
      setNotice(`已保存。修订号 ${saved.revision}。`);
      onSaved(saved);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 409) {
        setConflict(error.message);
        return;
      }
      const message = error instanceof ApiError ? error.message : "保存失败。";
      setNotice(message);
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="editor-form" onSubmit={save}>
      <div className="editor-meta">
        <label>
          章节标题
          <input
            value={title}
            maxLength={200}
            onChange={(event) => {
              setTitle(event.target.value);
            }}
          />
        </label>
        <label>
          状态
          <select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as ChapterStatus);
            }}
          >
            {STATUSES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <p className="hint">
          修订号 {revision} · 已保存字数 {wordCount}
        </p>
      </div>
      <label className="editor-body">
        正文
        <textarea
          value={draft}
          rows={16}
          spellCheck
          onChange={(event) => {
            setDraft(event.target.value);
            setNotice("");
          }}
          aria-describedby="editor-hint"
        />
      </label>
      <p id="editor-hint" className="hint">
        空行分段。保存时写成 {CANONICAL_CONTENT_FORMAT}。这里不会自动保存。
      </p>
      {conflict ? (
        <p className="banner banner-error" role="alert">
          {conflict} 当前输入仍留在编辑区，没有被服务器正文覆盖。
        </p>
      ) : null}
      {notice ? (
        <p className="banner" role="status">
          {notice}
        </p>
      ) : null}
      <div className="editor-actions">
        <button className="primary" type="submit" disabled={pending || title.trim() === ""}>
          保存正文
        </button>
        {conflict ? (
          <button
            className="ghost"
            type="button"
            disabled={pending}
            onClick={() => {
              void loadServerCopy();
            }}
          >
            载入服务器正文
          </button>
        ) : null}
      </div>
      <details className="json-preview" open>
        <summary>将保存的 Tiptap JSON</summary>
        <pre>{JSON.stringify(document, null, 2)}</pre>
      </details>
    </form>
  );
}
