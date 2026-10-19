import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listEntities } from "../api/memory.ts";
import {
  confirmChapterOutline,
  confirmStoryPlan,
  getChapterOutline,
  getStoryPlan,
  listChapterOutlines,
  listScenes,
  reorderScenes,
  saveChapterOutline,
  saveStoryPlan,
  type ChapterOutline,
  type SceneCard,
  type StoryPlan,
} from "../api/planning.ts";
import type { ChapterSummary } from "../api/types.ts";
import { ChapterPlanEditor, OutlinePanel } from "./OutlinePanel.tsx";

vi.mock("../api/planning.ts", async () => {
  const actual = await vi.importActual<typeof import("../api/planning.ts")>("../api/planning.ts");
  return {
    ...actual,
    getStoryPlan: vi.fn(),
    saveStoryPlan: vi.fn(),
    confirmStoryPlan: vi.fn(),
    listChapterOutlines: vi.fn(),
    getChapterOutline: vi.fn(),
    saveChapterOutline: vi.fn(),
    confirmChapterOutline: vi.fn(),
    listScenes: vi.fn(),
    createScene: vi.fn(),
    updateScene: vi.fn(),
    deleteScene: vi.fn(),
    reorderScenes: vi.fn(),
  };
});

vi.mock("../api/memory.ts", () => ({
  listEntities: vi.fn(async () => []),
}));

const chapters: ChapterSummary[] = [
  {
    id: "chapter-1",
    novel_id: "novel-1",
    volume_id: null,
    title: "城门",
    sort_order: 0,
    word_count: 12,
    status: "draft",
    revision: 2,
    updated_at: "2026-01-01T00:00:00Z",
  },
];

const draftPlan: StoryPlan = {
  id: "plan-1",
  novel_id: "novel-1",
  logline: "城门关早了",
  body: "上卷找钥匙",
  ending_intent: null,
  status: "draft",
  revision: 1,
  counts_as_fact: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const draftOutline: ChapterOutline = {
  id: "outline-1",
  novel_id: "novel-1",
  chapter_id: "chapter-1",
  goal: "发现钟是坏的",
  must_advance: null,
  required_events: null,
  allowed_reveals: null,
  forbidden_reveals: "不能写城里空了",
  target_words: null,
  ending_hook: null,
  status: "draft",
  revision: 1,
  counts_as_fact: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function scene(id: string, goal: string, sortOrder: number, status: SceneCard["status"]): SceneCard {
  return {
    id,
    novel_id: "novel-1",
    chapter_id: "chapter-1",
    sort_order: sortOrder,
    goal,
    location_entity_id: null,
    location: null,
    character_entity_ids: [],
    characters: [],
    conflict: null,
    turning_point: null,
    expected_outcome: null,
    must_convey: null,
    must_not_reveal: null,
    status,
    revision: 1,
    counts_as_fact: status === "confirmed",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("OutlinePanel", () => {
  beforeEach(() => {
    vi.mocked(getStoryPlan).mockReset();
    vi.mocked(saveStoryPlan).mockReset();
    vi.mocked(confirmStoryPlan).mockReset();
    vi.mocked(listChapterOutlines).mockReset();
    vi.mocked(getStoryPlan).mockResolvedValue({ novel_id: "novel-1", plan: null });
    vi.mocked(listChapterOutlines).mockResolvedValue([]);
  });

  it("saves a draft novel outline and confirms it without treating the draft as fact", async () => {
    const user = userEvent.setup();
    render(
      <OutlinePanel
        novelId="novel-1"
        chapters={chapters}
        activeChapterId={null}
        onOpenChapter={() => {}}
      />,
    );

    expect((await screen.findAllByText("无大纲")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("未确认，不会当作强制事实。").length).toBeGreaterThan(0);
    await user.type(screen.getByLabelText("作品大纲一句话"), "城门关早了");
    vi.mocked(saveStoryPlan).mockResolvedValue(draftPlan);
    await user.click(screen.getByRole("button", { name: "保存作品大纲" }));

    expect(saveStoryPlan).toHaveBeenCalledWith("novel-1", {
      logline: "城门关早了",
      body: null,
      ending_intent: null,
      status: "draft",
      expected_revision: undefined,
    });
    expect((await screen.findAllByText("草稿")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("未确认，不会当作强制事实。").length).toBeGreaterThan(0);

    vi.mocked(confirmStoryPlan).mockResolvedValue({
      ...draftPlan,
      status: "confirmed",
      revision: 2,
      counts_as_fact: true,
    });
    await user.click(screen.getByRole("button", { name: "确认作品大纲" }));
    expect(confirmStoryPlan).toHaveBeenCalledWith("novel-1", 1);
    expect(await screen.findByText("已确认。之后才会当作创作约束。")).toBeTruthy();
  });
});

describe("ChapterPlanEditor", () => {
  beforeEach(() => {
    vi.mocked(getChapterOutline).mockReset();
    vi.mocked(saveChapterOutline).mockReset();
    vi.mocked(confirmChapterOutline).mockReset();
    vi.mocked(listScenes).mockReset();
    vi.mocked(reorderScenes).mockReset();
    vi.mocked(listEntities).mockReset();
    vi.mocked(listEntities).mockResolvedValue([]);
    vi.mocked(listScenes).mockResolvedValue([]);
  });

  it("lets a chapter without an outline stay writable", async () => {
    const user = userEvent.setup();
    vi.mocked(getChapterOutline).mockResolvedValue({
      novel_id: "novel-1",
      chapter_id: "chapter-1",
      outline: null,
    });
    render(<ChapterPlanEditor novelId="novel-1" chapterId="chapter-1" chapterTitle="城门" />);

    expect(await screen.findByText(/没有大纲也可以写正文/)).toBeTruthy();
    expect(screen.getByText(/未确认的大纲不会当作强制事实/)).toBeTruthy();
    vi.mocked(saveChapterOutline).mockResolvedValue(draftOutline);
    await user.click(screen.getByRole("button", { name: "写下章节大纲" }));
    expect(saveChapterOutline).toHaveBeenCalledWith("chapter-1", { status: "draft" });
    expect(await screen.findByLabelText("章节目标")).toHaveProperty("value", "发现钟是坏的");
  });

  it("confirms a chapter outline and reorders scene cards", async () => {
    const user = userEvent.setup();
    const first = scene("scene-1", "问钟", 0, "draft");
    const second = scene("scene-2", "回钥匙孔", 1, "confirmed");
    vi.mocked(getChapterOutline).mockResolvedValue({
      novel_id: "novel-1",
      chapter_id: "chapter-1",
      outline: draftOutline,
    });
    vi.mocked(listScenes).mockResolvedValue([first, second]);
    render(<ChapterPlanEditor novelId="novel-1" chapterId="chapter-1" chapterTitle="城门" />);

    expect(await screen.findByDisplayValue("问钟")).toBeTruthy();
    expect(screen.getByDisplayValue("回钥匙孔")).toBeTruthy();
    expect(screen.getAllByText("未确认，不会当作强制事实。").length).toBeGreaterThan(0);
    expect(screen.getByText("已确认。之后才会当作创作约束。")).toBeTruthy();

    vi.mocked(confirmChapterOutline).mockResolvedValue({
      ...draftOutline,
      status: "confirmed",
      revision: 2,
      counts_as_fact: true,
    });
    await user.click(screen.getByRole("button", { name: "确认章节大纲" }));
    expect(confirmChapterOutline).toHaveBeenCalledWith("chapter-1", 1);

    vi.mocked(reorderScenes).mockResolvedValue([
      { ...second, sort_order: 0 },
      { ...first, sort_order: 1 },
    ]);
    await user.click(screen.getAllByRole("button", { name: "下移场景" })[0]!);
    expect(reorderScenes).toHaveBeenCalledWith("chapter-1", ["scene-2", "scene-1"]);
    const goals = screen.getAllByLabelText(/场景目标/);
    expect((goals[0] as HTMLInputElement).value).toBe("回钥匙孔");
    expect((goals[1] as HTMLInputElement).value).toBe("问钟");
  });
});
