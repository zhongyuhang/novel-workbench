import { useEffect, useLayoutEffect, useRef, useState, type DragEvent } from "react";
import type { ChapterSummary, Volume } from "../api/types.ts";
import {
  moveVolumeToStart,
  planChapterMove,
  planVolumeMove,
  type DropPlace,
} from "../features/toc/reorder.ts";

export type TocGroup = {
  key: string;
  title: string;
  volumeId: string | null;
  volume: Volume | null;
  chapters: ChapterSummary[];
};

type TocDrag =
  | { kind: "chapter"; id: string; volumeId: string | null }
  | { kind: "volume"; id: string };

type MenuState = {
  key: string;
  top: number;
  left: number;
};

type TocTreeProps = {
  groups: TocGroup[];
  volumeIds: string[];
  chapterId: string | null;
  busy: boolean;
  renamingId: string | null;
  renameValue: string;
  onRenameValue: (value: string) => void;
  onStartRename: (volume: Volume) => void;
  onSubmitRename: (volume: Volume) => void;
  onOpenChapter: (id: string) => void;
  onCreateChapter: (volumeId: string | null) => void;
  onMoveChapter: (chapterId: string, volumeId: string | null, sortOrder: number) => void;
  onReorderVolumes: (volumeIds: string[]) => void;
  onShiftVolume: (volumeId: string, direction: -1 | 1) => void;
  onDuplicateChapter: (chapterId: string) => void;
  onDeleteChapter: (chapter: ChapterSummary) => void;
  onDeleteVolume: (volume: Volume) => void;
  onAnalyzeChapter: (chapter: ChapterSummary) => void;
};

const DRAG_MIME = "application/x-novel-toc";
const MENU_WIDTH_REM = 13;

function rootFontSize(): number {
  const size = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
  return Number.isFinite(size) && size > 0 ? size : 15;
}

function placeMenuLeft(anchor: HTMLElement, width: number): number {
  const rect = anchor.getBoundingClientRect();
  const rail = anchor.closest(".toc-pane")?.getBoundingClientRect();
  const minLeft = Math.max(8, (rail?.left ?? 0) + 8);
  const maxLeft = Math.max(minLeft, (rail?.right ?? window.innerWidth) - 8 - width);
  return Math.min(Math.max(rect.right - width, minLeft), maxLeft);
}

export function TocTree({
  groups,
  volumeIds,
  chapterId,
  busy,
  renamingId,
  renameValue,
  onRenameValue,
  onStartRename,
  onSubmitRename,
  onOpenChapter,
  onCreateChapter,
  onMoveChapter,
  onReorderVolumes,
  onShiftVolume,
  onDuplicateChapter,
  onDeleteChapter,
  onDeleteVolume,
  onAnalyzeChapter,
}: TocTreeProps) {
  const dragRef = useRef<TocDrag | null>(null);
  const menuAnchorRef = useRef<HTMLElement | null>(null);
  const menuNodeRef = useRef<HTMLDivElement | null>(null);
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [dropKey, setDropKey] = useState<string | null>(null);

  useEffect(() => {
    if (!menu) {
      return;
    }
    const close = () => {
      setMenu(null);
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && target.closest(".toc-menu, .toc-more")) {
        return;
      }
      close();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        close();
      }
    };
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [menu]);

  useLayoutEffect(() => {
    const node = menuNodeRef.current;
    const anchor = menuAnchorRef.current;
    if (!menu || !node || !anchor) {
      return;
    }
    const box = node.getBoundingClientRect();
    const rect = anchor.getBoundingClientRect();
    const width = box.width > 0 ? box.width : MENU_WIDTH_REM * rootFontSize();
    const height = box.height;
    let top = rect.bottom + 4;
    if (height > 0 && top + height > window.innerHeight - 8) {
      const above = rect.top - height - 4;
      if (above >= 8) {
        top = above;
      }
    }
    const left = placeMenuLeft(anchor, width);
    const nextTop = Math.round(top);
    const nextLeft = Math.round(left);
    if (nextTop !== menu.top || nextLeft !== menu.left) {
      setMenu({ ...menu, top: nextTop, left: nextLeft });
    }
  }, [menu]);

  function openMenu(key: string, anchor: HTMLElement) {
    menuAnchorRef.current = anchor;
    const rect = anchor.getBoundingClientRect();
    const width = MENU_WIDTH_REM * rootFontSize();
    setMenu({
      key,
      top: Math.round(rect.bottom + 4),
      left: Math.round(placeMenuLeft(anchor, width)),
    });
  }

  function beginDrag(event: DragEvent, payload: TocDrag) {
    const target = event.target;
    if (target instanceof Element && target.closest(".toc-more, .toc-menu")) {
      event.preventDefault();
      return;
    }
    dragRef.current = payload;
    event.dataTransfer.setData(DRAG_MIME, JSON.stringify(payload));
    event.dataTransfer.effectAllowed = "move";
  }

  function placeFromEvent(event: DragEvent): DropPlace {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.height <= 0) {
      return "before";
    }
    return event.clientY - rect.top > rect.height / 2 ? "after" : "before";
  }

  function dropChapter(target: TocGroup, targetId: string | null, place: DropPlace | "end") {
    const drag = dragRef.current;
    dragRef.current = null;
    setDropKey(null);
    if (!drag || drag.kind !== "chapter") {
      return;
    }
    const source = groups.find((group) => group.volumeId === drag.volumeId);
    const sourceIds = source?.chapters.map((item) => item.id) ?? [];
    const targetIds = target.chapters.map((item) => item.id);
    const index = planChapterMove(sourceIds, drag.id, targetIds, targetId, place);
    if (index === null) {
      return;
    }
    onMoveChapter(drag.id, target.volumeId, index);
  }

  function dropVolume(targetId: string | null, place: DropPlace | "start") {
    const drag = dragRef.current;
    dragRef.current = null;
    setDropKey(null);
    if (!drag || drag.kind !== "volume") {
      return;
    }
    const next =
      place === "start" || targetId === null
        ? moveVolumeToStart(volumeIds, drag.id)
        : planVolumeMove(volumeIds, drag.id, targetId, place);
    if (!next) {
      return;
    }
    onReorderVolumes(next);
  }

  const menuChapterId = menu?.key.startsWith("chapter:") ? menu.key.slice("chapter:".length) : null;
  const menuVolumeId = menu?.key.startsWith("volume:") ? menu.key.slice("volume:".length) : null;
  const menuGroup = groups.find(
    (group) => group.volume?.id === menuVolumeId || group.chapters.some((item) => item.id === menuChapterId),
  );
  const menuChapter = menuGroup?.chapters.find((item) => item.id === menuChapterId) ?? null;
  const menuVolume = groups.find((group) => group.volume?.id === menuVolumeId)?.volume ?? null;

  return (
    <>
      {groups.map((group) => (
        <section
          key={group.key}
          className={`toc-group${dropKey === group.key ? " is-drop-target" : ""}`}
          onDragOver={(event) => {
            if (!dragRef.current) {
              return;
            }
            event.preventDefault();
            setDropKey(group.key);
          }}
          onDragLeave={(event) => {
            if (event.currentTarget.contains(event.relatedTarget as Node | null)) {
              return;
            }
            setDropKey((current) => (current === group.key ? null : current));
          }}
          onDrop={(event) => {
            event.preventDefault();
            const drag = dragRef.current;
            if (!drag) {
              return;
            }
            if (drag.kind === "chapter") {
              dropChapter(group, null, "end");
              return;
            }
            if (!group.volume) {
              dropVolume(null, "start");
              return;
            }
            dropVolume(group.volume.id, placeFromEvent(event));
          }}
        >
          <div
            className="toc-group-head"
            draggable={group.volume !== null}
            onDragStart={(event) => {
              if (!group.volume) {
                event.preventDefault();
                return;
              }
              beginDrag(event, { kind: "volume", id: group.volume.id });
            }}
            onDragEnd={() => {
              dragRef.current = null;
              setDropKey(null);
            }}
          >
            {renamingId === group.volume?.id && group.volume ? (
              <form
                className="rename-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!group.volume) {
                    return;
                  }
                  onSubmitRename(group.volume);
                }}
              >
                <input
                  value={renameValue}
                  aria-label="卷标题"
                  onChange={(event) => {
                    onRenameValue(event.target.value);
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
              <button
                className="toc-more"
                type="button"
                aria-haspopup="menu"
                aria-expanded={menu?.key === `volume:${group.volume.id}`}
                aria-label={`${group.title}的操作`}
                onClick={(event) => {
                  event.stopPropagation();
                  const key = `volume:${group.volume?.id ?? group.key}`;
                  if (menu?.key === key) {
                    setMenu(null);
                    return;
                  }
                  openMenu(key, event.currentTarget);
                }}
              >
                ⋯
              </button>
            ) : null}
          </div>
          <ol className="toc-list">
            {group.chapters.map((item) => (
              <li
                key={item.id}
                className={item.id === chapterId ? "toc-current" : undefined}
                draggable
                onDragStart={(event) => {
                  beginDrag(event, { kind: "chapter", id: item.id, volumeId: group.volumeId });
                }}
                onDragEnd={() => {
                  dragRef.current = null;
                  setDropKey(null);
                }}
                onDragOver={(event) => {
                  if (dragRef.current?.kind !== "chapter") {
                    return;
                  }
                  event.preventDefault();
                  event.stopPropagation();
                  setDropKey(item.id);
                }}
                onDrop={(event) => {
                  if (dragRef.current?.kind !== "chapter") {
                    return;
                  }
                  event.preventDefault();
                  event.stopPropagation();
                  dropChapter(group, item.id, placeFromEvent(event));
                }}
                onContextMenu={(event) => {
                  event.preventDefault();
                  const more = event.currentTarget.querySelector(".toc-more");
                  openMenu(
                    `chapter:${item.id}`,
                    more instanceof HTMLElement ? more : event.currentTarget,
                  );
                }}
              >
                <div className={`toc-row${dropKey === item.id ? " is-drop-target" : ""}`}>
                  <button
                    className="toc-link"
                    type="button"
                    aria-label={`${item.title}，${item.word_count} 字`}
                    onClick={() => {
                      onOpenChapter(item.id);
                    }}
                  >
                    <span>{item.title}</span>
                    <span className="hint">{item.word_count} 字</span>
                  </button>
                  <button
                    className="toc-more"
                    type="button"
                    aria-haspopup="menu"
                    aria-expanded={menu?.key === `chapter:${item.id}`}
                    aria-label={`${item.title}的操作`}
                    onClick={(event) => {
                      event.stopPropagation();
                      const key = `chapter:${item.id}`;
                      if (menu?.key === key) {
                        setMenu(null);
                        return;
                      }
                      openMenu(key, event.currentTarget);
                    }}
                  >
                    ⋯
                  </button>
                </div>
              </li>
            ))}
          </ol>
          <button
            className="ghost"
            type="button"
            disabled={busy}
            onClick={() => {
              onCreateChapter(group.volumeId);
            }}
          >
            在此新建章节
          </button>
        </section>
      ))}
      {menu && menuChapter ? (
        <div
          ref={menuNodeRef}
          className="menu-panel toc-menu"
          role="menu"
          style={{ top: menu.top, left: menu.left }}
          aria-label={`${menuChapter.title}的操作`}
        >
          <button
            className="ghost"
            type="button"
            role="menuitem"
            disabled={busy || menuGroup?.chapters[0]?.id === menuChapter.id}
            onClick={() => {
              const index = menuGroup?.chapters.findIndex((item) => item.id === menuChapter.id) ?? 0;
              setMenu(null);
              if (!menuGroup || index <= 0) {
                return;
              }
              onMoveChapter(menuChapter.id, menuGroup.volumeId, index - 1);
            }}
          >
            上移
          </button>
          <button
            className="ghost"
            type="button"
            role="menuitem"
            disabled={busy || menuGroup?.chapters.at(-1)?.id === menuChapter.id}
            onClick={() => {
              const index = menuGroup?.chapters.findIndex((item) => item.id === menuChapter.id) ?? 0;
              setMenu(null);
              if (!menuGroup || index < 0 || index >= menuGroup.chapters.length - 1) {
                return;
              }
              onMoveChapter(menuChapter.id, menuGroup.volumeId, index + 1);
            }}
          >
            下移
          </button>
          <button
            className="ghost"
            type="button"
            role="menuitem"
            disabled={busy}
            onClick={() => {
              setMenu(null);
              onDuplicateChapter(menuChapter.id);
            }}
          >
            复制
          </button>
          <button
            className="ghost"
            type="button"
            role="menuitem"
            disabled={busy}
            onClick={() => {
              setMenu(null);
              onAnalyzeChapter(menuChapter);
            }}
          >
            分析记忆
          </button>
          <div className="menu-divider" role="separator" />
          <button
            className="danger"
            type="button"
            role="menuitem"
            disabled={busy}
            onClick={() => {
              setMenu(null);
              onDeleteChapter(menuChapter);
            }}
          >
            删除
          </button>
        </div>
      ) : null}
      {menu && menuVolume ? (
        <div
          ref={menuNodeRef}
          className="menu-panel toc-menu"
          role="menu"
          style={{ top: menu.top, left: menu.left }}
          aria-label={`${menuVolume.title}的操作`}
        >
          <button
            className="ghost"
            type="button"
            role="menuitem"
            disabled={busy || menuVolume.sort_order === 0}
            onClick={() => {
              setMenu(null);
              onShiftVolume(menuVolume.id, -1);
            }}
          >
            上移
          </button>
          <button
            className="ghost"
            type="button"
            role="menuitem"
            disabled={busy || menuVolume.sort_order === volumeIds.length - 1}
            onClick={() => {
              setMenu(null);
              onShiftVolume(menuVolume.id, 1);
            }}
          >
            下移
          </button>
          <button
            className="ghost"
            type="button"
            role="menuitem"
            disabled={busy}
            onClick={() => {
              setMenu(null);
              onStartRename(menuVolume);
            }}
          >
            改名
          </button>
          <div className="menu-divider" role="separator" />
          <button
            className="danger"
            type="button"
            role="menuitem"
            disabled={busy}
            onClick={() => {
              setMenu(null);
              onDeleteVolume(menuVolume);
            }}
          >
            删除卷
          </button>
        </div>
      ) : null}
    </>
  );
}

export function buildToc(volumes: Volume[], chapters: ChapterSummary[]): TocGroup[] {
  const groups: TocGroup[] = [
    {
      key: "unassigned",
      title: "未分卷",
      volumeId: null,
      volume: null,
      chapters: chapters.filter((item) => item.volume_id === null),
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
