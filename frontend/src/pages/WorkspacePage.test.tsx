import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { deleteChapter, getChapter, getNovel, listChapters, listVolumes } from "../api/catalog.ts";
import { getHealth } from "../api/client.ts";
import { getChapterOutline, getStoryPlan, listChapterOutlines, listScenes } from "../api/planning.ts";
import type { Chapter, ChapterSummary, Novel, Volume } from "../api/types.ts";
import { WorkspacePage } from "./WorkspacePage.tsx";

vi.mock("../api/client.ts", async () => {
  const actual = await vi.importActual<typeof import("../api/client.ts")>("../api/client.ts");
  return {
    ...actual,
    getHealth: vi.fn(async () => ({
      status: "ok",
      service: "api",
      version: "1.0.0",
      database: "ok",
    })),
  };
});

vi.mock("../api/catalog.ts", () => ({
  cleanupShellChapters: vi.fn(async () => ({ deleted: 0 })),
  createChapter: vi.fn(),
  createVolume: vi.fn(),
  deleteChapter: vi.fn(),
  deleteVolume: vi.fn(),
  duplicateChapter: vi.fn(),
  exportNovel: vi.fn(),
  getChapter: vi.fn(),
  getNovel: vi.fn(),
  listChapters: vi.fn(),
  listVolumes: vi.fn(),
  moveChapter: vi.fn(),
  reorderVolumes: vi.fn(),
  updateVolume: vi.fn(),
  saveChapter: vi.fn(),
  listChapterVersions: vi.fn(async () => []),
  restoreChapter: vi.fn(),
}));

vi.mock("../api/planning.ts", async () => {
  const actual = await vi.importActual<typeof import("../api/planning.ts")>("../api/planning.ts");
  return {
    ...actual,
    getStoryPlan: vi.fn(),
    listChapterOutlines: vi.fn(),
    getChapterOutline: vi.fn(),
    listScenes: vi.fn(),
    saveChapterOutline: vi.fn(),
  };
});

vi.mock("../api/memory.ts", () => ({
  listEntities: vi.fn(async () => []),
}));

vi.mock("../components/AiPanel.tsx", async () => {
  const React = await import("react");
  return {
    AiPanel: (props: {
      onActivity?: (activity: { phase: "background"; message: string } | null) => void;
    }) => {
      const onActivity = props.onActivity;
      React.useEffect(() => {
        onActivity?.({
          phase: "background",
          message: "仍在后台生成。可以稍后查看。",
        });
      }, [onActivity]);
      return React.createElement("aside", null, "生成面板");
    },
  };
});

vi.mock("../components/MemoryPanel.tsx", () => ({
  MemoryPanel: () => <aside>设定面板</aside>,
}));

vi.mock("../components/QualityPanel.tsx", () => ({
  QualityPanel: () => <aside>质量面板</aside>,
}));

vi.mock("../components/IdeationPanel.tsx", () => ({
  IdeationPanel: () => <aside>创意面板</aside>,
}));

vi.mock("../components/ChroniclePanel.tsx", () => ({
  ChroniclePanel: () => <aside>编年史面板</aside>,
}));

const novel: Novel = {
  id: "novel-1",
  title: "城门",
  genre: null,
  synopsis: null,
  style_guide: null,
  core_conflict: null,
  status: "draft",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const summary: ChapterSummary = {
  id: "chapter-1",
  novel_id: "novel-1",
  volume_id: null,
  title: "第一章",
  sort_order: 0,
  word_count: 4,
  status: "draft",
  revision: 1,
  updated_at: "2026-01-01T00:00:00Z",
};

const chapter: Chapter = {
  ...summary,
  created_at: "2026-01-01T00:00:00Z",
  content_format: "tiptap_json",
  content_format_version: 1,
  content: {
    type: "doc",
    content: [{ type: "paragraph", content: [{ type: "text", text: "原句还在" }] }],
  },
};

describe("WorkspacePage planning view", () => {
  beforeEach(() => {
    vi.mocked(getHealth).mockClear();
    vi.mocked(getNovel).mockResolvedValue(novel);
    vi.mocked(listVolumes).mockResolvedValue([]);
    vi.mocked(listChapters).mockResolvedValue([summary]);
    vi.mocked(getChapter).mockResolvedValue(chapter);
    vi.mocked(getStoryPlan).mockResolvedValue({ novel_id: novel.id, plan: null });
    vi.mocked(listChapterOutlines).mockResolvedValue([]);
    vi.mocked(getChapterOutline).mockResolvedValue({
      novel_id: novel.id,
      chapter_id: chapter.id,
      outline: null,
    });
    vi.mocked(listScenes).mockResolvedValue([]);
    localStorage.removeItem("novel-workbench-focus");
  });

  it("keeps the catalog and adds an outline view", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage novelId={novel.id} chapterId={chapter.id} />);

    expect(await screen.findByRole("tab", { name: "目录" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "新建卷" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "第一章，4 字" })).toBeTruthy();
    expect(screen.getByText("过短")).toBeTruthy();
    expect(await screen.findByText("原句还在")).toBeTruthy();

    await user.click(screen.getByRole("tab", { name: "大纲" }));
    expect(await screen.findByRole("heading", { name: "作品大纲" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "新建卷" })).toBeNull();

    await user.click(screen.getByRole("tab", { name: "目录" }));
    expect(screen.getByRole("button", { name: "在此新建章节" })).toBeTruthy();

    await user.click(screen.getByRole("tab", { name: "章节大纲" }));
    expect(await screen.findByText(/没有大纲也可以写正文/)).toBeTruthy();
    expect(screen.queryByText("原句还在")).toBeNull();

    await user.click(screen.getByRole("tab", { name: "正文" }));
    expect(await screen.findByText("原句还在")).toBeTruthy();

    const ideation = screen.getByRole("tab", { name: "创意" });
    await user.click(ideation);
    expect(ideation.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("创意面板")).toBeTruthy();

    const chronicle = screen.getByRole("tab", { name: "编年史" });
    await user.click(chronicle);
    expect(chronicle.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("编年史面板")).toBeTruthy();
  });

  it("keeps chapter actions in the row menu and confirms delete", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<WorkspacePage novelId={novel.id} chapterId={chapter.id} />);

    expect(await screen.findByRole("button", { name: "第一章的操作" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "删除" })).toBeNull();
    expect(screen.queryByRole("button", { name: "分析记忆" })).toBeNull();
    expect(screen.queryByRole("button", { name: "上移" })).toBeNull();

    const opener = screen.getByRole("button", { name: "第一章的操作" });
    opener.getBoundingClientRect = () => new DOMRect(220, 140, 36, 40);
    const pane = opener.closest(".toc-pane");
    expect(pane).toBeTruthy();
    pane!.getBoundingClientRect = () => new DOMRect(0, 48, 272, 700);
    await user.click(opener);
    const menu = screen.getByRole("menu", { name: "第一章的操作" });
    expect(screen.getByRole("menuitem", { name: "分析记忆" })).toBeTruthy();
    const items = screen.getAllByRole("menuitem");
    expect(items.at(-1)?.textContent).toBe("删除");
    expect(menu.classList.contains("toc-menu")).toBe(true);
    expect(menu.classList.contains("menu-panel")).toBe(true);
    const font = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
    const width = 13 * (Number.isFinite(font) && font > 0 ? font : 15);
    const left = Number.parseFloat(menu.style.left);
    expect(left).toBeGreaterThanOrEqual(8);
    expect(left + width).toBeLessThanOrEqual(272 - 8 + 0.5);

    await user.click(screen.getByRole("menuitem", { name: "删除" }));
    expect(confirm).toHaveBeenCalled();
    expect(deleteChapter).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("enters focus mode, remembers it, and leaves with Escape", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage novelId={novel.id} chapterId={chapter.id} />);

    await user.click(await screen.findByRole("button", { name: "专注" }));

    expect(document.querySelector(".workspace")?.classList.contains("is-focus")).toBe(true);
    expect(screen.queryByRole("link", { name: "返回作品库" })).toBeNull();
    expect(screen.getByRole("button", { name: "退出专注" })).toBeTruthy();
    expect(screen.getByText("仍在后台生成。可以稍后查看。")).toBeTruthy();
    expect(localStorage.getItem("novel-workbench-focus")).toBe("1");

    await user.keyboard("{Escape}");

    expect(document.querySelector(".workspace")?.classList.contains("is-focus")).toBe(false);
    expect(screen.getByRole("button", { name: "专注" })).toBeTruthy();
    expect(localStorage.getItem("novel-workbench-focus")).toBe("0");
  });

  it("keeps volume and right-click menus compact", async () => {
    const user = userEvent.setup();
    const volume: Volume = {
      id: "vol-1",
      novel_id: novel.id,
      title: "第一卷",
      sort_order: 0,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    vi.mocked(listVolumes).mockResolvedValue([volume]);
    vi.mocked(listChapters).mockResolvedValue([
      { ...summary, volume_id: volume.id, title: "第三章", sort_order: 2 },
    ]);
    render(<WorkspacePage novelId={novel.id} chapterId={chapter.id} />);

    await user.click(await screen.findByRole("button", { name: "第一卷的操作" }));
    const volumeMenu = screen.getByRole("menu", { name: "第一卷的操作" });
    expect(volumeMenu.classList.contains("toc-menu")).toBe(true);
    expect(Number.parseFloat(volumeMenu.style.left)).toBeLessThan(320);
    const volumeItems = screen.getAllByRole("menuitem");
    expect(volumeItems.at(-1)?.textContent).toBe("删除卷");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();

    const row = screen.getByRole("button", { name: "第三章，4 字" }).closest("li");
    expect(row).toBeTruthy();
    fireEvent.contextMenu(row!);
    const chapterMenu = screen.getByRole("menu", { name: "第三章的操作" });
    expect(chapterMenu.classList.contains("toc-menu")).toBe(true);
    expect(Number.parseFloat(chapterMenu.style.left)).toBeLessThan(320);
    expect(screen.getAllByRole("menuitem").at(-1)?.textContent).toBe("删除");
  });
});
