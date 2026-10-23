import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listModelConfigs } from "../api/models.ts";
import {
  acceptProposal,
  analyzeChapter,
  createEntityState,
  createRelation,
  deferProposal,
  listChapterSummaries,
  listEntities,
  listEvents,
  listProposals,
  listRelations,
  markIntentionalProposal,
  materialImpact,
  rejectProposal,
  type EntityRelation,
  type MemoryProposal,
  type StoryEntity,
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
  listRelations: vi.fn(),
  analyzeChapter: vi.fn(),
  acceptProposal: vi.fn(),
  rejectProposal: vi.fn(),
  deferProposal: vi.fn(),
  markIntentionalProposal: vi.fn(),
  materialImpact: vi.fn(),
  revertProposal: vi.fn(),
  createEntity: vi.fn(),
  updateEntity: vi.fn(),
  createRelation: vi.fn(),
  deleteRelation: vi.fn(),
  createEntityState: vi.fn(),
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
    vi.mocked(listRelations).mockResolvedValue([]);
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

    await user.click(await screen.findByRole("button", { name: "忽略" }));

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

    expect(analyzeChapter).toHaveBeenCalledWith("chapter-1", {
      revision: 3,
      use_mock: true,
      scope: "full",
    });
    expect(await screen.findByText(/正式设定和正文都没有自动改动/)).toBeTruthy();
    expect(acceptProposal).not.toHaveBeenCalled();
  });

  it("filters relations by storyline and keeps evidence visible", async () => {
    const lin: StoryEntity = {
      id: "entity-lin",
      novel_id: "novel-1",
      entity_type: "character",
      name: "林晚",
      aliases: [],
      profile: { summary: "守城人" },
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      states: [
        {
          id: "state-1",
          entity_id: "entity-lin",
          chapter_id: "chapter-1",
          chapter_title: "开篇",
          source_revision: 3,
          state_data: { summary: "左臂旧伤" },
          evidence_quote: "左臂的旧伤又疼了起来。",
          source_type: "manual",
          valid_from_text: null,
          valid_until_text: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    };
    const gate: StoryEntity = {
      ...lin,
      id: "entity-gate",
      name: "城门",
      entity_type: "location",
      profile: {},
      states: [],
    };
    const mainRelation: EntityRelation = {
      id: "relation-1",
      novel_id: "novel-1",
      from_entity_id: "entity-lin",
      from_entity_name: "林晚",
      to_entity_id: "entity-gate",
      to_entity_name: "城门",
      relation_type: "驻守",
      story_time_text: null,
      storyline: "主线",
      source_chapter_id: "chapter-1",
      source_chapter_title: "开篇",
      source_revision: 3,
      evidence_quote: "林晚仍驻守在城门。",
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    const sideRelation: EntityRelation = {
      ...mainRelation,
      id: "relation-2",
      relation_type: "路过",
      storyline: "支线",
      evidence_quote: "有人路过城门。",
    };
    vi.mocked(listEntities).mockResolvedValue([lin, gate]);
    vi.mocked(listRelations).mockResolvedValue([mainRelation, sideRelation]);
    vi.mocked(listProposals).mockResolvedValue([]);
    const user = userEvent.setup();
    render(
      <MemoryPanel
        novelId="novel-1"
        activeChapterId="chapter-1"
        activeRevision={3}
        activeTitle="开篇"
        editorDirty={false}
        chapters={[{ id: "chapter-1", title: "开篇" }]}
      />,
    );

    expect(await screen.findByText("证据：林晚仍驻守在城门。")).toBeTruthy();
    expect(screen.getAllByText("证据：左臂的旧伤又疼了起来。").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/有效时间未填写/).length).toBeGreaterThan(0);
    await user.type(screen.getByRole("textbox", { name: "按故事线筛选" }), "主线");
    expect(screen.getAllByText(/驻守/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/路过/)).toBeNull();
    expect(screen.getByText("证据：林晚仍驻守在城门。")).toBeTruthy();
  });

  it("records a relation without story time", async () => {
    const lin: StoryEntity = {
      id: "entity-lin",
      novel_id: "novel-1",
      entity_type: "character",
      name: "林晚",
      aliases: [],
      profile: {},
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      states: [],
    };
    const gate: StoryEntity = {
      ...lin,
      id: "entity-gate",
      name: "城门",
      entity_type: "location",
    };
    vi.mocked(listEntities).mockResolvedValue([lin, gate]);
    vi.mocked(listProposals).mockResolvedValue([]);
    vi.mocked(createRelation).mockResolvedValue({
      id: "relation-1",
      novel_id: "novel-1",
      from_entity_id: "entity-lin",
      from_entity_name: "林晚",
      to_entity_id: "entity-gate",
      to_entity_name: "城门",
      relation_type: "驻守",
      story_time_text: null,
      storyline: null,
      source_chapter_id: null,
      source_chapter_title: null,
      source_revision: null,
      evidence_quote: null,
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
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

    await user.selectOptions(await screen.findByRole("combobox", { name: "关系起点" }), "entity-lin");
    await user.selectOptions(screen.getByRole("combobox", { name: "关系终点" }), "entity-gate");
    await user.type(screen.getByRole("textbox", { name: "关系类型" }), "驻守");
    await user.click(screen.getByRole("button", { name: "记录关系" }));

    expect(createRelation).toHaveBeenCalledWith("novel-1", {
      from_entity_id: "entity-lin",
      to_entity_id: "entity-gate",
      relation_type: "驻守",
      story_time_text: null,
      storyline: null,
      source_chapter_id: null,
      evidence_quote: null,
      status: "active",
    });
    expect(createEntityState).not.toHaveBeenCalled();
  });

  it("runs a light check without treating it as a full model analysis", async () => {
    vi.mocked(analyzeChapter).mockResolvedValue({
      chapter_id: "chapter-1",
      novel_id: "novel-1",
      source_revision: 3,
      status: "completed",
      provider_mode: "rule",
      model_name: "轻量检查",
      prompt_version: "analyze_chapter_v1",
      proposal_count: 0,
      proposals: [],
      message: "轻量检查没有调用模型，也没有新的候选。正式设定没有改动。",
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

    await user.click(await screen.findByRole("button", { name: "轻量检查" }));

    expect(analyzeChapter).toHaveBeenCalledWith("chapter-1", {
      revision: 3,
      use_mock: false,
      scope: "light",
    });
    expect(await screen.findByText(/轻量检查没有调用模型/)).toBeTruthy();
    expect(acceptProposal).not.toHaveBeenCalled();
  });

  it("defers a proposal without accepting it", async () => {
    vi.mocked(deferProposal).mockResolvedValue({ ...proposal, status: "deferred" });
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

    await user.click(await screen.findByRole("button", { name: "延后" }));

    expect(deferProposal).toHaveBeenCalledWith("proposal-1");
    expect(acceptProposal).not.toHaveBeenCalled();
    expect(markIntentionalProposal).not.toHaveBeenCalled();
    expect(materialImpact).not.toHaveBeenCalled();
  });
});
