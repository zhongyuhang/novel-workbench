import { useEffect, useState, type FormEvent } from "react";
import { apiDocsUrl } from "../api/client.ts";
import { createNovel, deleteNovel, listNovels, updateNovel } from "../api/catalog.ts";
import {
  createBackup,
  importPortable,
  listBackups,
  previewPortable,
  type PortablePreview,
} from "../api/portable.ts";
import { ApiError, type Novel, type NovelDraft, type NovelStatus } from "../api/types.ts";
import { HealthBadge } from "../components/HealthBadge.tsx";
import { LibraryMaintenance } from "../components/LibraryMaintenance.tsx";
import {
  CANONICAL_CONTENT_FORMAT,
  CANONICAL_CONTENT_FORMAT_VERSION,
} from "../editor/contentFormat.ts";
import { useBackendHealth } from "../features/library/useBackendHealth.ts";

const EMPTY_DRAFT: NovelDraft = {
  title: "",
  genre: "",
  synopsis: "",
  style_guide: "",
  core_conflict: "",
  status: "draft",
};

const STATUS_LABEL: Record<NovelStatus, string> = {
  draft: "草稿",
  active: "连载中",
  archived: "已归档",
};

export function NovelLibraryPage() {
  const health = useBackendHealth();
  const [novels, setNovels] = useState<Novel[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [latestBackup, setLatestBackup] = useState<string | null>(null);
  const [backupPending, setBackupPending] = useState(false);
  const [packageFile, setPackageFile] = useState<File | null>(null);
  const [packagePreview, setPackagePreview] = useState<PortablePreview | null>(null);
  const [packageError, setPackageError] = useState("");
  const [importPending, setImportPending] = useState(false);

  async function refresh() {
    setError("");
    try {
      setNovels(await listNovels());
    } catch (cause: unknown) {
      if (cause instanceof DOMException && cause.name === "AbortError") {
        return;
      }
      setError(cause instanceof ApiError ? cause.message : "无法读取作品列表。");
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    listBackups(controller.signal)
      .then((report) => {
        setLatestBackup(report.latest_success_at);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") {
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "无法读取备份记录。");
      });
    listNovels(controller.signal)
      .then((items) => {
        setNovels(items);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") {
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "无法读取作品列表。");
      });
    return () => {
      controller.abort();
    };
  }, []);

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          <p className="eyebrow">个人长篇</p>
          <p className="wordmark">AI Novel Writer</p>
        </div>
        <div className="topbar-meta">
          <p className="milestone">M3 作品库</p>
          <a className="ghost" href="#/settings">
            模型设置
          </a>
          <HealthBadge state={health} />
        </div>
      </header>
      <main className="main">
        <section className="intro">
          <h1>作品库</h1>
          <p>创建、修改和归档作品。打开这一页不需要模型 API Key。正文在作品工作台里保存。</p>
        </section>
        <LibraryMaintenance
          latestSuccessAt={latestBackup}
          backupPending={backupPending}
          onBackup={() => {
            setBackupPending(true);
            setError("");
            void createBackup()
              .then((item) => {
                setLatestBackup(item.created_at);
              })
              .catch((cause: unknown) => {
                setError(cause instanceof ApiError ? cause.message : "备份没有完成。");
              })
              .finally(() => {
                setBackupPending(false);
              });
          }}
          preview={packagePreview}
          previewError={packageError}
          importPending={importPending}
          onChooseFile={(file) => {
            setPackageFile(file);
            setPackageError("");
            setPackagePreview(null);
            void previewPortable(file)
              .then((report) => {
                setPackagePreview(report);
              })
              .catch((cause: unknown) => {
                setPackageError(cause instanceof ApiError ? cause.message : "作品包无法预检。");
              });
          }}
          onConfirmImport={() => {
            if (!packageFile || !packagePreview?.can_import) {
              return;
            }
            setImportPending(true);
            setError("");
            void importPortable(packageFile)
              .then(async () => {
                setPackageFile(null);
                setPackagePreview(null);
                await refresh();
              })
              .catch((cause: unknown) => {
                setError(cause instanceof ApiError ? cause.message : "导入没有完成。");
              })
              .finally(() => {
                setImportPending(false);
              });
          }}
          onCancelPreview={() => {
            setPackageFile(null);
            setPackagePreview(null);
            setPackageError("");
          }}
        />
        <section className="library" aria-labelledby="library-heading">
          <div className="library-toolbar">
            <h2 id="library-heading">作品</h2>
            <button
              type="button"
              className="primary"
              onClick={() => {
                setCreating((current) => !current);
                setEditingId(null);
              }}
            >
              {creating ? "取消新建" : "新建作品"}
            </button>
          </div>
          {error ? (
            <p className="banner banner-error" role="alert">
              {error}
            </p>
          ) : null}
          {creating ? (
            <NovelForm
              initial={EMPTY_DRAFT}
              submitLabel="创建"
              onCancel={() => {
                setCreating(false);
              }}
              onSubmit={async (draft) => {
                await createNovel(toPayload(draft));
                setCreating(false);
                await refresh();
              }}
            />
          ) : null}
          {novels === null ? <p role="status">正在读取作品</p> : null}
          {novels?.length === 0 ? (
            <div className="empty">
              <p className="empty-title">还没有作品</p>
              <p>用「新建作品」写下标题。这里不会展示虚构的样例小说。</p>
            </div>
          ) : null}
          <ul className="novel-list">
            {novels?.map((novel) => (
              <li key={novel.id}>
                <div className="novel-row">
                  <div>
                    <h3>{novel.title}</h3>
                    <p className="hint">
                      {STATUS_LABEL[novel.status]}
                      {novel.genre ? ` · ${novel.genre}` : ""}
                      {` · ${formatTime(novel.updated_at)}`}
                    </p>
                  </div>
                  <div className="inline-actions">
                    <a className="primary link-button" href={`#/novels/${novel.id}`}>
                      打开
                    </a>
                    <button
                      className="ghost"
                      type="button"
                      onClick={() => {
                        setEditingId((current) => (current === novel.id ? null : novel.id));
                        setCreating(false);
                      }}
                    >
                      编辑
                    </button>
                    <button
                      className="ghost"
                      type="button"
                      onClick={() => {
                        void updateNovel(novel.id, {
                          status: novel.status === "archived" ? "active" : "archived",
                        })
                          .then(() => refresh())
                          .catch((cause: unknown) => {
                            setError(cause instanceof ApiError ? cause.message : "归档没有完成。");
                          });
                      }}
                    >
                      {novel.status === "archived" ? "恢复" : "归档"}
                    </button>
                    <button
                      className="ghost danger"
                      type="button"
                      onClick={() => {
                        if (!window.confirm(`删除「${novel.title}」？删除后不再出现在作品库。`)) {
                          return;
                        }
                        void deleteNovel(novel.id)
                          .then(() => refresh())
                          .catch((cause: unknown) => {
                            setError(cause instanceof ApiError ? cause.message : "删除没有完成。");
                          });
                      }}
                    >
                      删除
                    </button>
                  </div>
                </div>
                {editingId === novel.id ? (
                  <NovelForm
                    initial={{
                      title: novel.title,
                      genre: novel.genre ?? "",
                      synopsis: novel.synopsis ?? "",
                      style_guide: novel.style_guide ?? "",
                      core_conflict: novel.core_conflict ?? "",
                      status: novel.status,
                    }}
                    submitLabel="保存修改"
                    onCancel={() => {
                      setEditingId(null);
                    }}
                    onSubmit={async (draft) => {
                      await updateNovel(novel.id, toPayload(draft));
                      setEditingId(null);
                      await refresh();
                    }}
                  />
                ) : null}
              </li>
            ))}
          </ul>
        </section>
        <p className="format-note">
          权威正文格式：
          <code>
            {CANONICAL_CONTENT_FORMAT} v{CANONICAL_CONTENT_FORMAT_VERSION}
          </code>
          。接口说明见 <a href={apiDocsUrl}>API 文档</a>。
        </p>
      </main>
    </div>
  );
}

function NovelForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  initial: NovelDraft;
  submitLabel: string;
  onSubmit: (draft: NovelDraft) => Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      await onSubmit(draft);
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "保存没有完成。");
      setPending(false);
    }
  }

  return (
    <form className="stack-form" onSubmit={submit}>
      <label>
        标题
        <input
          required
          maxLength={200}
          value={draft.title}
          onChange={(event) => {
            setDraft({ ...draft, title: event.target.value });
          }}
        />
      </label>
      <label>
        类型
        <input
          maxLength={100}
          value={draft.genre}
          onChange={(event) => {
            setDraft({ ...draft, genre: event.target.value });
          }}
        />
      </label>
      <label>
        简介
        <textarea
          rows={3}
          maxLength={20000}
          value={draft.synopsis}
          onChange={(event) => {
            setDraft({ ...draft, synopsis: event.target.value });
          }}
        />
      </label>
      <label>
        核心冲突
        <textarea
          rows={3}
          maxLength={20000}
          value={draft.core_conflict}
          onChange={(event) => {
            setDraft({ ...draft, core_conflict: event.target.value });
          }}
        />
      </label>
      <label>
        文风备注
        <textarea
          rows={3}
          maxLength={20000}
          value={draft.style_guide}
          onChange={(event) => {
            setDraft({ ...draft, style_guide: event.target.value });
          }}
        />
      </label>
      <label>
        状态
        <select
          value={draft.status}
          onChange={(event) => {
            setDraft({ ...draft, status: event.target.value as NovelStatus });
          }}
        >
          <option value="draft">草稿</option>
          <option value="active">连载中</option>
          <option value="archived">已归档</option>
        </select>
      </label>
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="editor-actions">
        <button className="primary" type="submit" disabled={pending || draft.title.trim() === ""}>
          {submitLabel}
        </button>
        <button className="ghost" type="button" onClick={onCancel}>
          取消
        </button>
      </div>
    </form>
  );
}

function toPayload(draft: NovelDraft) {
  return {
    title: draft.title.trim(),
    genre: draft.genre.trim() || null,
    synopsis: draft.synopsis.trim() || null,
    style_guide: draft.style_guide.trim() || null,
    core_conflict: draft.core_conflict.trim() || null,
    status: draft.status,
  };
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
