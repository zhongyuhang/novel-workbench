import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  checkConflicts,
  getNovelStats,
  listForeshadowing,
  setWritingGoal,
  updateForeshadowing,
  type Foreshadowing,
  type NovelStats,
} from "../api/quality.ts";
import type { ChapterSummary } from "../api/types.ts";
import { QualityPanel } from "./QualityPanel.tsx";

vi.mock("../api/quality.ts", () => ({
  listForeshadowing: vi.fn(),
  createForeshadowing: vi.fn(),
  updateForeshadowing: vi.fn(),
  checkConflicts: vi.fn(),
  getNovelStats: vi.fn(),
  setWritingGoal: vi.fn(),
}));

const chapters: ChapterSummary[] = [
  {
    id: "chapter-1",
    novel_id: "novel-1",
    volume_id: null,
    title: "开篇",
    sort_order: 0,
    word_count: 12,
    status: "draft",
    revision: 2,
    updated_at: "2026-01-01T00:00:00Z",
  },
];

const openItem: Foreshadowing = {
  id: "hint-1",
  novel_id: "novel-1",
  introduced_chapter_id: "chapter-1",
  description: "抽屉里的钥匙",
  status: "open",
  payoff_chapter_id: null,
  evidence_quote: "钥匙还在",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const resolvedItem: Foreshadowing = {
  ...openItem,
  id: "hint-2",
  description: "已经打开的门",
  status: "resolved",
  updated_at: "2026-01-02T00:00:00Z",
};

const stats: NovelStats = {
  novel_id: "novel-1",
  total_word_count: 12,
  chapter_count: 1,
  target_words: null,
  chapters: [
    {
      chapter_id: "chapter-1",
      title: "开篇",
      volume_id: null,
      sort_order: 0,
      word_count: 12,
    },
  ],
};

describe("QualityPanel", () => {
  beforeEach(() => {
    vi.mocked(listForeshadowing).mockReset();
    vi.mocked(updateForeshadowing).mockReset();
    vi.mocked(checkConflicts).mockReset();
    vi.mocked(getNovelStats).mockReset();
    vi.mocked(setWritingGoal).mockReset();
    vi.mocked(getNovelStats).mockResolvedValue(stats);
    vi.mocked(listForeshadowing).mockImplementation(async (_novelId, status) =>
      status === "open" ? [openItem] : [openItem, resolvedItem],
    );
  });

  it("filters foreshadowing and saves a status change", async () => {
    const user = userEvent.setup();
    render(
      <QualityPanel novelId="novel-1" chapters={chapters} activeChapterId="chapter-1" refreshKey="1" />,
    );

    expect(await screen.findByDisplayValue("抽屉里的钥匙")).toBeTruthy();
    expect(screen.getByDisplayValue("已经打开的门")).toBeTruthy();
    expect(screen.getByText(/全本 12 字/)).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("伏笔状态"), "open");
    await waitFor(() => {
      expect(screen.queryByDisplayValue("已经打开的门")).toBeNull();
    });
    expect(screen.getByDisplayValue("抽屉里的钥匙")).toBeTruthy();

    await user.selectOptions(screen.getByLabelText(`伏笔状态 ${openItem.id}`), "planned");
    vi.mocked(updateForeshadowing).mockResolvedValue({ ...openItem, status: "planned" });
    await user.click(screen.getByRole("button", { name: "保存伏笔" }));

    expect(updateForeshadowing).toHaveBeenCalledWith(openItem.id, {
      description: "抽屉里的钥匙",
      status: "planned",
      payoff_chapter_id: null,
      evidence_quote: "钥匙还在",
    });
  });

  it("shows suspected conflicts without a control that writes memory", async () => {
    vi.mocked(checkConflicts).mockResolvedValue({
      chapter_id: "chapter-1",
      novel_id: "novel-1",
      provider_mode: "mock",
      prompt_version: "conflict_check_v1",
      manuscript_changed: false,
      formal_memory_changed: false,
      message: "已用本地规则检查疑似冲突。正文和正式记忆都没有改动。",
      conflicts: [
        {
          conflict_type: "attribute_contradiction",
          manuscript_snippet: "阿宁是右撇子。",
          confirmed_fact: "阿宁是左撇子",
          source_chapter_id: "chapter-1",
          source_chapter_title: "开篇",
          source_quote: "阿宁是左撇子",
          severity: "medium",
          confidence: 0.74,
          suggested_action: "请人工核对。系统不会自动修改正文或正式记忆。",
        },
      ],
    });
    const user = userEvent.setup();
    render(
      <QualityPanel novelId="novel-1" chapters={chapters} activeChapterId="chapter-1" refreshKey="1" />,
    );

    await user.click(await screen.findByRole("button", { name: "检查疑似冲突" }));

    expect(checkConflicts).toHaveBeenCalledWith("chapter-1");
    expect(await screen.findByText(/阿宁是右撇子/)).toBeTruthy();
    expect(screen.getByText("阿宁是左撇子")).toBeTruthy();
    expect(screen.getByText(/来源章节：开篇/)).toBeTruthy();
    expect(screen.getByText(/不会自动修改正文或正式记忆/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /写入记忆|自动改/ })).toBeNull();
  });

  it("saves a word-count goal", async () => {
    vi.mocked(setWritingGoal).mockResolvedValue({ ...stats, target_words: 1000 });
    const user = userEvent.setup();
    render(
      <QualityPanel novelId="novel-1" chapters={chapters} activeChapterId="chapter-1" refreshKey="1" />,
    );

    await user.type(await screen.findByLabelText("目标字数"), "1000");
    await user.click(screen.getByRole("button", { name: "保存目标" }));

    expect(setWritingGoal).toHaveBeenCalledWith("novel-1", 1000);
    expect(await screen.findByText(/目标 1000 字/)).toBeTruthy();
  });
});
