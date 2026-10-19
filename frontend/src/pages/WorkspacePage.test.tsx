import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getChapter, getNovel, listChapters, listVolumes } from "../api/catalog.ts";
import { getHealth } from "../api/client.ts";
import { getChapterOutline, getStoryPlan, listChapterOutlines, listScenes } from "../api/planning.ts";
import type { Chapter, ChapterSummary, Novel } from "../api/types.ts";
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

vi.mock("../components/AiPanel.tsx", () => ({
  AiPanel: () => <aside>生成面板</aside>,
}));

vi.mock("../components/MemoryPanel.tsx", () => ({
  MemoryPanel: () => <aside>设定面板</aside>,
}));

vi.mock("../components/QualityPanel.tsx", () => ({
  QualityPanel: () => <aside>质量面板</aside>,
}));

const novel: Novel = {
  id: "novel-1",
  title: "城门",
  genre: null,
  synopsis: null,
  style_guide: null,
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
  });

  it("keeps the catalog and adds an outline view", async () => {
    const user = userEvent.setup();
    render(<WorkspacePage novelId={novel.id} chapterId={chapter.id} />);

    expect(await screen.findByRole("tab", { name: "目录" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "新建卷" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /第一章/ })).toBeTruthy();
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
  });
});
