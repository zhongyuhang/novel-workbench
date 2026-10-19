import { useEffect, useRef, useState } from "react";
import {
  createChapter,
  createVolume,
  deleteChapter,
  deleteVolume,
  duplicateChapter,
  exportNovel,
  getChapter,
  getNovel,
  listChapters,
  listVolumes,
  moveChapter,
  reorderVolumes,
  updateVolume,
} from "../api/catalog.ts";
import { ApiError, type Chapter, type ChapterSummary, type Novel, type Volume } from "../api/types.ts";
import { AiPanel } from "../components/AiPanel.tsx";
import { ChapterEditor } from "../components/ChapterEditor.tsx";
import { MemoryPanel } from "../components/MemoryPanel.tsx";
import { ChapterPlanEditor, OutlinePanel } from "../components/OutlinePanel.tsx";
import { QualityPanel } from "../components/QualityPanel.tsx";
import { requestMemoryAnalyze } from "../features/memory/analyzeBridge.ts";
import { HealthBadge } from "../components/HealthBadge.tsx";
import { allowChapterLeave } from "../editor/leaveGuard.ts";
import { useBackendHealth } from "../features/library/useBackendHealth.ts";
import { parseHash, workspaceHash } from "../routes.ts";

type WorkspacePageProps = {
  novelId: string;
  chapterId: string | null;
};

type TocGroup = {
  key: string;
  title: string;
  volumeId: string | null;
  volume: Volume | null;
  chapters: ChapterSummary[];
};

export function WorkspacePage({ novelId, chapterId }: WorkspacePageProps) {
  const health = useBackendHealth();
  const [novel, setNovel] = useState<Novel | null>(null);
  const [volumes, setVolumes] = useState<Volume[]>([]);
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [error, setError] = useState("");
  const [unsaved, setUnsaved] = useState(false);
  const [selectionText, setSelectionText] = useState("");
  const [adoptedChapter, setAdoptedChapter] = useState<Chapter | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [sideTab, setSideTab] = useState<"write" | "memory" | "quality">("write");
  const [leftView, setLeftView] = useState<"toc" | "outline">("toc");
  const [centerView, setCenterView] = useState<"manuscript" | "outline">("manuscript");
  const unsavedRef = useRef(false);
  const skipGuardRef = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError("");
    Promise.all([
      getNovel(novelId, controller.signal),
      listVolumes(novelId, controller.signal),
      listChapters(novelId, controller.signal),
    ])
      .then(([nextNovel, nextVolumes, nextChapters]) => {
        if (!active) {
          return;
        }
        setNovel(nextNovel);
        setVolumes(nextVolumes);
        setChapters(nextChapters);
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setError(messageFrom(cause, "无法读取作品结构。"));
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [novelId]);

  useEffect(() => {
    if (!chapterId) {
      setChapter(null);
      setSelectionText("");
      setAdoptedChapter(null);
      return;
    }
    setSelectionText("");
    setAdoptedChapter(null);
    const controller = new AbortController();
    let active = true;
    getChapter(chapterId, controller.signal)
      .then((next) => {
        if (active) {
          setChapter(next);
          setError("");
        }
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setChapter(null);
        setError(messageFrom(cause, "无法读取章节。"));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [chapterId]);

  async function refreshStructure() {
    const [nextVolumes, nextChapters] = await Promise.all([
      listVolumes(novelId),
      listChapters(novelId),
    ]);
    setVolumes(nextVolumes);
    setChapters(nextChapters);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (cause: unknown) {
      setError(messageFrom(cause, "操作没有完成。"));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const onHashChange = () => {
      if (skipGuardRef.current) {
        skipGuardRef.current = false;
        return;
      }
      if (!unsavedRef.current || chapterId === null) {
        return;
      }
      const next = parseHash(window.location.hash);
      const sameChapter =
        next.kind === "workspace" && next.novelId === novelId && next.chapterId === chapterId;
      if (sameChapter) {
        return;
      }
      if (!allowChapterLeave(true, (message) => window.confirm(message))) {
        skipGuardRef.current = true;
        window.location.hash = workspaceHash(novelId, chapterId);
      }
    };
    window.addEventListener("hashchange", onHashChange);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
    };
  }, [chapterId, novelId]);

  function tryNavigate(hash: string) {
    if (!allowChapterLeave(unsavedRef.current, (message) => window.confirm(message))) {
      return;
    }
    if (window.location.hash === hash) {
      return;
    }
    skipGuardRef.current = true;
    window.location.hash = hash;
  }

  function forceNavigate(hash: string) {
    if (window.location.hash === hash) {
      return;
    }
    skipGuardRef.current = true;
    window.location.hash = hash;
  }

  function openChapter(id: string) {
    tryNavigate(workspaceHash(novelId, id));
  }

  function openChapterIn(id: string, view: "manuscript" | "outline") {
    const leavingManuscript =
      centerView === "manuscript" && (id !== chapterId || view !== "manuscript");
    if (
      leavingManuscript &&
      !allowChapterLeave(unsavedRef.current, (message) => window.confirm(message))
    ) {
      return;
    }
    setCenterView(view);
    if (id === chapterId) {
      return;
    }
    forceNavigate(workspaceHash(novelId, id));
  }

  const toc = buildToc(volumes, chapters);

  return (
    <div className="workspace">
      <header className="workspace-top">
        <a
          className="ghost back-link"
          href="#/"
          onClick={(event) => {
            event.preventDefault();
            tryNavigate("#/");
          }}
        >
          返回作品库
        </a>
        <div>
          <p className="eyebrow">作品</p>
          <h1>{novel?.title ?? "读取中"}</h1>
        </div>
        <div className="topbar-meta">
          <p className="milestone">E1 叙事规划</p>
          <a className="ghost" href="#/settings">
            模型设置
          </a>
          <div className="inline-actions">
            <button
              className="ghost"
              type="button"
              disabled={busy || !novel}
              onClick={() => {
                void run(async () => {
                  await downloadExport(novelId, "markdown");
                });
              }}
            >
              导出 Markdown
            </button>
            <button
              className="ghost"
              type="button"
              disabled={busy || !novel}
              onClick={() => {
                void run(async () => {
                  await downloadExport(novelId, "txt");
                });
              }}
            >
              导出 TXT
            </button>
          </div>
          <HealthBadge state={health} />
        </div>
      </header>
      {error ? (
        <p className="banner banner-error workspace-banner" role="alert">
          {error}
        </p>
      ) : null}
      <div className="workspace-columns">
        <nav className="workspace-pane toc-pane" aria-label="目录与大纲">
          <div className="pane-toolbar">
            <div className="view-tabs" role="tablist" aria-label="左栏视图">
              <button
                className={leftView === "toc" ? "primary" : "ghost"}
                type="button"
                role="tab"
                aria-selected={leftView === "toc"}
                onClick={() => {
                  setLeftView("toc");
                }}
              >
                目录
              </button>
              <button
                className={leftView === "outline" ? "primary" : "ghost"}
                type="button"
                role="tab"
                aria-selected={leftView === "outline"}
                onClick={() => {
                  setLeftView("outline");
                }}
              >
                大纲
              </button>
            </div>
            {leftView === "toc" ? (
              <h2 className="visually-hidden">目录</h2>
            ) : null}
            <button
              hidden={leftView !== "toc"}
              className="ghost"
              type="button"
              disabled={busy || loading}
              onClick={() => {
                void run(async () => {
                  await createVolume(novelId, "新卷");
                  await refreshStructure();
                });
              }}
            >
              新建卷
            </button>
          </div>
          {leftView === "outline" ? (
            <OutlinePanel
              novelId={novelId}
              chapters={chapters}
              activeChapterId={chapterId}
              onOpenChapter={(id) => {
                openChapterIn(id, "outline");
              }}
            />
          ) : null}
          {leftView === "toc" && loading ? <p role="status">正在读取目录</p> : null}
          {leftView === "toc" && !loading && chapters.length === 0 && volumes.length === 0 ? (
            <p className="hint">还没有卷或章节。</p>
          ) : null}
          {leftView === "toc"
            ? toc.map((group) => (
            <section key={group.key} className="toc-group">
              <div className="toc-group-head">
                {renamingId === group.volume?.id ? (
                  <form
                    className="rename-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const volume = group.volume;
                      if (!volume) {
                        return;
                      }
                      void run(async () => {
                        await updateVolume(volume.id, renameValue.trim());
                        setRenamingId(null);
                        await refreshStructure();
                      });
                    }}
                  >
                    <input
                      value={renameValue}
                      aria-label="卷标题"
                      onChange={(event) => {
                        setRenameValue(event.target.value);
                      }}
                    />
                    <button className="ghost" type="submit" disabled={renameValue.trim() === ""}>
                      保存
                    </button>
                  </form>
                ) : (
                  <h3>{group.title}</h3>
                )}
                {group.volume ? (
                  <div className="inline-actions">
                    <button
                      className="ghost"
                      type="button"
                      disabled={busy || group.volume.sort_order === 0}
                      onClick={() => {
                        const volume = group.volume;
                        if (!volume) {
                          return;
                        }
                        void run(async () => {
                          await shiftVolume(novelId, volumes, volume.id, -1);
                          await refreshStructure();
                        });
                      }}
                    >
                      上移
                    </button>
                    <button
                      className="ghost"
                      type="button"
                      disabled={busy || group.volume.sort_order === volumes.length - 1}
                      onClick={() => {
                        const volume = group.volume;
                        if (!volume) {
                          return;
                        }
                        void run(async () => {
                          await shiftVolume(novelId, volumes, volume.id, 1);
                          await refreshStructure();
                        });
                      }}
                    >
                      下移
                    </button>
                    <button
                      className="ghost"
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        if (!group.volume) {
                          return;
                        }
                        setRenamingId(group.volume.id);
                        setRenameValue(group.volume.title);
                      }}
                    >
                      改名
                    </button>
                    <button
                      className="ghost danger"
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        const volume = group.volume;
                        if (!volume) {
                          return;
                        }
                        if (!window.confirm(`删除「${volume.title}」？其中的章节会移到未分卷。`)) {
                          return;
                        }
                        void run(async () => {
                          await deleteVolume(volume.id);
                          await refreshStructure();
                        });
                      }}
                    >
                      删除卷
                    </button>
                  </div>
                ) : null}
              </div>
              <ol className="toc-list">
                {group.chapters.map((item, index) => (
                  <li key={item.id} className={item.id === chapterId ? "toc-current" : undefined}>
                    <button
                      className="toc-link"
                      type="button"
                      onClick={() => {
                        openChapterIn(item.id, "manuscript");
                      }}
                    >
                      <span>{item.title}</span>
                      <span className="hint">{item.word_count} 字</span>
                    </button>
                    <div className="inline-actions">
                      <button
                        className="ghost"
                        type="button"
                        disabled={busy || index === 0}
                        onClick={() => {
                          void run(async () => {
                            await moveChapter(item.id, group.volumeId, index - 1);
                            await refreshStructure();
                          });
                        }}
                      >
                        上移
                      </button>
                      <button
                        className="ghost"
                        type="button"
                        disabled={busy || index === group.chapters.length - 1}
                        onClick={() => {
                          void run(async () => {
                            await moveChapter(item.id, group.volumeId, index + 1);
                            await refreshStructure();
                          });
                        }}
                      >
                        下移
                      </button>
                      <button
                        className="ghost"
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          void run(async () => {
                            const copy = await duplicateChapter(item.id);
                            await refreshStructure();
                            openChapter(copy.id);
                          });
                        }}
                      >
                        复制
                      </button>
                      <button
                        className="ghost"
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          if (item.id === chapterId && unsaved) {
                            setError("正文还有未保存的修改。请先保存，再分析这一章。");
                            return;
                          }
                          setSideTab("memory");
                          requestMemoryAnalyze({
                            chapterId: item.id,
                            revision: item.revision,
                            title: item.title,
                          });
                        }}
                      >
                        分析记忆
                      </button>
                      <button
                        className="ghost danger"
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          if (!window.confirm(`删除章节「${item.title}」？`)) {
                            return;
                          }
                          void run(async () => {
                            await deleteChapter(item.id);
                            await refreshStructure();
                            if (chapterId === item.id) {
                              forceNavigate(workspaceHash(novelId, null));
                            }
                          });
                        }}
                      >
                        删除
                      </button>
                    </div>
                  </li>
                ))}
              </ol>
              <button
                className="ghost"
                type="button"
                disabled={busy || loading}
                onClick={() => {
                  void run(async () => {
                    const created = await createChapter(novelId, "未命名章节", group.volumeId);
                    await refreshStructure();
                    openChapter(created.id);
                  });
                }}
              >
                在此新建章节
              </button>
            </section>
          ))
            : null}
        </nav>
        <main className="workspace-pane editor-pane">
          {chapter && chapter.id === chapterId ? (
            <div className="view-tabs" role="tablist" aria-label="章节视图">
              <button
                className={centerView === "manuscript" ? "primary" : "ghost"}
                type="button"
                role="tab"
                aria-selected={centerView === "manuscript"}
                onClick={() => {
                  if (!chapter) {
                    return;
                  }
                  openChapterIn(chapter.id, "manuscript");
                }}
              >
                正文
              </button>
              <button
                className={centerView === "outline" ? "primary" : "ghost"}
                type="button"
                role="tab"
                aria-selected={centerView === "outline"}
                onClick={() => {
                  if (!chapter) {
                    return;
                  }
                  openChapterIn(chapter.id, "outline");
                }}
              >
                章节大纲
              </button>
            </div>
          ) : null}
          {chapter && chapter.id === chapterId && centerView === "outline" ? (
            <ChapterPlanEditor
              key={`${novelId}:${chapter.id}`}
              novelId={novelId}
              chapterId={chapter.id}
              chapterTitle={chapter.title}
            />
          ) : null}
          {chapter && chapter.id === chapterId && centerView === "manuscript" ? (
            <ChapterEditor
              key={chapter.id}
              chapter={chapter}
              onUnsavedChange={(value) => {
                unsavedRef.current = value;
                setUnsaved(value);
              }}
              onSelectionChange={setSelectionText}
              adoptedChapter={adoptedChapter}
              onSaved={(saved) => {
                setChapter(saved);
                setChapters((current) =>
                  current.map((item) =>
                    item.id === saved.id
                      ? {
                          ...item,
                          title: saved.title,
                          status: saved.status,
                          word_count: saved.word_count,
                          revision: saved.revision,
                          updated_at: saved.updated_at,
                        }
                      : item,
                  ),
                );
              }}
            />
          ) : null}
          {!chapter || chapter.id !== chapterId ? (
            <div className="empty">
              <p className="empty-title">{chapterId ? "正在打开章节" : "选择一章"}</p>
              <p>从左侧目录打开章节，或在未分卷下新建。正文保存在服务器，刷新后仍在。</p>
            </div>
          ) : null}
        </main>
        <div className="side-pane">
          <div className="side-tabs" role="tablist" aria-label="写作侧栏">
            <button
              className={sideTab === "write" ? "primary" : "ghost"}
              type="button"
              role="tab"
              aria-selected={sideTab === "write"}
              onClick={() => {
                setSideTab("write");
              }}
            >
              生成
            </button>
            <button
              className={sideTab === "memory" ? "primary" : "ghost"}
              type="button"
              role="tab"
              aria-selected={sideTab === "memory"}
              onClick={() => {
                setSideTab("memory");
              }}
            >
              设定
            </button>
            <button
              className={sideTab === "quality" ? "primary" : "ghost"}
              type="button"
              role="tab"
              aria-selected={sideTab === "quality"}
              onClick={() => {
                setSideTab("quality");
              }}
            >
              质量
            </button>
          </div>
          <div hidden={sideTab !== "write"}>
            <AiPanel
              novelId={novelId}
              chapter={chapter}
              savedRevision={chapter?.revision ?? null}
              selectionText={selectionText}
              editorDirty={unsaved}
              onAccepted={(saved) => {
                setChapter(saved);
                setAdoptedChapter(saved);
                setChapters((current) =>
                  current.map((item) =>
                    item.id === saved.id
                      ? {
                          ...item,
                          title: saved.title,
                          status: saved.status,
                          word_count: saved.word_count,
                          revision: saved.revision,
                          updated_at: saved.updated_at,
                        }
                      : item,
                  ),
                );
              }}
            />
          </div>
          <div hidden={sideTab !== "quality"}>
            <QualityPanel
              novelId={novelId}
              chapters={chapters}
              activeChapterId={chapterId}
              refreshKey={`${chapter?.revision ?? 0}:${chapters.map((item) => item.word_count).join(",")}`}
              onManuscriptUpdated={(saved) => {
                setChapter(saved);
                setAdoptedChapter(saved);
                setChapters((current) =>
                  current.map((item) =>
                    item.id === saved.id
                      ? {
                          ...item,
                          title: saved.title,
                          status: saved.status,
                          word_count: saved.word_count,
                          revision: saved.revision,
                          updated_at: saved.updated_at,
                        }
                      : item,
                  ),
                );
              }}
            />
          </div>
          <div hidden={sideTab !== "memory"}>
            <MemoryPanel
              novelId={novelId}
              activeChapterId={chapterId}
              activeRevision={chapter?.revision ?? null}
              activeTitle={chapter?.title ?? null}
              editorDirty={unsaved}
              chapters={chapters}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function buildToc(volumes: Volume[], chapters: ChapterSummary[]): TocGroup[] {
  const unassigned = chapters.filter((item) => item.volume_id === null);
  const groups: TocGroup[] = [
    {
      key: "unassigned",
      title: "未分卷",
      volumeId: null,
      volume: null,
      chapters: unassigned,
    },
  ];
  for (const volume of volumes) {
    groups.push({
      key: volume.id,
      title: volume.title,
      volumeId: volume.id,
      volume,
      chapters: chapters.filter((item) => item.volume_id === volume.id),
    });
  }
  return groups;
}

async function shiftVolume(
  novelId: string,
  volumes: Volume[],
  volumeId: string,
  direction: -1 | 1,
) {
  const ids = volumes.map((volume) => volume.id);
  const index = ids.indexOf(volumeId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= ids.length) {
    return;
  }
  const next = ids[target];
  if (!next) {
    return;
  }
  ids[target] = volumeId;
  ids[index] = next;
  await reorderVolumes(novelId, ids);
}

async function downloadExport(novelId: string, format: "markdown" | "txt") {
  const file = await exportNovel(novelId, format);
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = file.filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
