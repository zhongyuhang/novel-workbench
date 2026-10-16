import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listModelConfigs } from "../api/models.ts";
import {
  acceptProposal,
  analyzeChapter,
  listChapterSummaries,
  listEntities,
  listEvents,
  listProposals,
  rejectProposal,
  type MemoryProposal,
} from "../api/memory.ts";
import { MemoryPanel } from "./MemoryPanel.tsx";

vi.mock("../api/models.ts", () => ({
  listModelConfigs: vi.fn(),
}));

vi.mock("../api/memory.ts", () => ({
  listEntities: vi.fn(),
  listProposals: vi.fn(),
  listChapterSummaries: vi.fn(),
  listEvents: vi.fn(),
  analyzeChapter: vi.fn(),
  acceptProposal: vi.fn(),
  rejectProposal: vi.fn(),
  revertProposal: vi.fn(),
  createEntity: vi.fn(),
  updateEntity: vi.fn(),
}));

const proposal: MemoryProposal = {
  id: "proposal-1",
  novel_id: "novel-1",
  source_chapter_id: "chapter-1",
  source_chapter_title: "开篇",
  source_revision: 3,
  proposal_type: "entity_create",
  payload: { name: "林晚" },
  evidence_quote: "林晚说道：夜里城门已经关了。",
  certainty: "confirmed",
  evidence_in_source: true,
  status: "pending",
  review_note: null,
  applied_entity_id: null,
  applied_state_id: null,
  applied_event_id: null,
  applied_summary_id: null,
  created_at: "2026-01-01T00:00:00Z",
  reviewed_at: null,
};

describe("MemoryPanel", () => {
  beforeEach(() => {
    vi.mocked(listModelConfigs).mockResolvedValue([]);
    vi.mocked(listEntities).mockResolvedValue([]);
    vi.mocked(listProposals).mockResolvedValue([proposal]);
    vi.mocked(listChapterSummaries).mockResolvedValue([
      {
        id: "summary-1",
        novel_id: "novel-1",
        chapter_id: "chapter-1",
        chapter_title: "开篇",
        summary: "旧摘要已经对不上正文。",
        key_facts: [],
        source_revision: 2,
        chapter_revision: 3,
        model_name: "模拟分析",
        status: "stale",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    vi.mocked(listEvents).mockResolvedValue([]);
    vi.mocked(acceptProposal).mockReset();
    vi.mocked(rejectProposal).mockReset();
    vi.mocked(analyzeChapter).mockReset();
  });

  it("shows evidence and does not accept a proposal on its own", async () => {
    render(
      <MemoryPanel
        novelId="novel-1"
        activeChapterId="chapter-1"
        activeRevision={3}
        activeTitle="开篇"
        editorDirty={false}
      />,
    );

    expect(await screen.findByText("林晚")).toBeTruthy();
    expect(screen.getByText("证据：林晚说道：夜里城门已经关了。")).toBeTruthy();
    expect(screen.getByText(/来源章节「开篇」修订 3/)).toBeTruthy();
    expect(screen.getByText("已过期摘要")).toBeTruthy();
    expect(screen.getByText("旧摘要已经对不上正文。")).toBeTruthy();
    expect(acceptProposal).not.toHaveBeenCalled();
  });

  it("rejects a proposal without accepting it", async () => {
    vi.mocked(rejectProposal).mockResolvedValue({ ...proposal, status: "rejected" });
    const user = userEvent.setup();
    render(
      <MemoryPanel
        novelId="novel-1"
        activeChapterId="chapter-1"
        activeRevision={3}
        activeTitle="开篇"
        editorDirty={false}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "拒绝" }));

    expect(rejectProposal).toHaveBeenCalledWith("proposal-1");
    expect(acceptProposal).not.toHaveBeenCalled();
  });

  it("keeps analysis results as proposals", async () => {
    vi.mocked(analyzeChapter).mockResolvedValue({
      chapter_id: "chapter-1",
      novel_id: "novel-1",
      source_revision: 3,
      status: "completed",
      provider_mode: "mock",
      model_name: "模拟分析",
      prompt_version: "analyze_chapter_v1",
      proposal_count: 1,
      proposals: [proposal],
      message: "模拟分析已生成提案。正式设定和正文都没有自动改动。",
      formal_memory_changed: false,
      manuscript_changed: false,
    });
    const user = userEvent.setup();
    render(
      <MemoryPanel
        novelId="novel-1"
        activeChapterId="chapter-1"
        activeRevision={3}
        activeTitle="开篇"
        editorDirty={false}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "分析当前章节" }));

    expect(analyzeChapter).toHaveBeenCalledWith("chapter-1", { revision: 3, use_mock: true });
    expect(await screen.findByText(/正式设定和正文都没有自动改动/)).toBeTruthy();
    expect(acceptProposal).not.toHaveBeenCalled();
  });
});
