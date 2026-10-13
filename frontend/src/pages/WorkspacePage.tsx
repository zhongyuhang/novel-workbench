import { useEffect, useState } from "react";
import {
  createChapter,
  createVolume,
  deleteChapter,
  deleteVolume,
  duplicateChapter,
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
import { ChapterDraft } from "../components/ChapterDraft.tsx";
import { HealthBadge } from "../components/HealthBadge.tsx";
import { useBackendHealth } from "../features/library/useBackendHealth.ts";

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
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

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
      return;
    }
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

  function openChapter(id: string) {
    window.location.hash = `#/novels/${novelId}/chapters/${id}`;
  }

  const toc = buildToc(volumes, chapters);

  return (
    <div className="workspace">
      <header className="workspace-top">
        <a className="ghost back-link" href="#/">
          返回作品库
        </a>
        <div>
          <p className="eyebrow">作品</p>
          <h1>{novel?.title ?? "读取中"}</h1>
        </div>
        <div className="topbar-meta">
          <p className="milestone">M1 目录与正文</p>
          <HealthBadge state={health} />
        </div>
      </header>
      {error ? (
        <p className="banner banner-error workspace-banner" role="alert">
          {error}
        </p>
      ) : null}
      <div className="workspace-columns">
        <nav className="workspace-pane toc-pane" aria-label="目录">
          <div className="pane-toolbar">
            <h2>目录</h2>
            <button
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
          {loading ? <p role="status">正在读取目录</p> : null}
          {!loading && chapters.length === 0 && volumes.length === 0 ? (
            <p className="hint">还没有卷或章节。</p>
          ) : null}
          {toc.map((group) => (
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
                        openChapter(item.id);
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
                              window.location.hash = `#/novels/${novelId}`;
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
          ))}
        </nav>
        <main className="workspace-pane editor-pane">
          {chapter ? (
            <ChapterDraft
              key={chapter.id}
              chapter={chapter}
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
          ) : (
            <div className="empty">
              <p className="empty-title">选择一章</p>
              <p>从左侧目录打开章节，或在未分卷下新建。正文保存在服务器，刷新后仍在。</p>
            </div>
          )}
        </main>
        <AiPanel />
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

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
