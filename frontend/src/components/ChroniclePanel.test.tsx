import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  acceptChronicleCandidate,
  createChronicleEvent,
  deferChronicleCandidate,
  deleteChronicleEvent,
  getChronicle,
  listChronicleCandidates,
  planChronicle,
  rejectChronicleCandidate,
  updateChronicleEvent,
  type ChronicleCandidate,
} from "../api/chronicle.ts";
import { listEntities, type StoryEventRecord } from "../api/memory.ts";
import { listModelConfigs } from "../api/models.ts";
import { listStoryArcs } from "../api/planning.ts";
import { listForeshadowing } from "../api/quality.ts";
import { ChroniclePanel } from "./ChroniclePanel.tsx";

vi.mock("../api/chronicle.ts", () => ({
  getChronicle: vi.fn(),
  listChronicleCandidates: vi.fn(),
  planChronicle: vi.fn(),
  acceptChronicleCandidate: vi.fn(),
  rejectChronicleCandidate: vi.fn(),
  deferChronicleCandidate: vi.fn(),
  createChronicleEvent: vi.fn(),
  deleteChronicleEvent: vi.fn(),
  updateChronicleEvent: vi.fn(),
}));

vi.mock("../api/memory.ts", () => ({
  listEntities: vi.fn(),
}));

vi.mock("../api/planning.ts", () => ({
  listStoryArcs: vi.fn(),
}));

vi.mock("../api/quality.ts", () => ({
  listForeshadowing: vi.fn(),
}));

vi.mock("../api/models.ts", () => ({
  listModelConfigs: vi.fn(),
}));

function event(partial: Partial<StoryEventRecord> & Pick<StoryEventRecord, "id" | "description">): StoryEventRecord {
  return {
    novel_id: "novel-1",
    chapter_id: null,
    chapter_title: "尚未关联章节",
    source_revision: null,
    chapter_revision: 0,
    title: null,
    event_time_text: null,
    sort_order: null,
    participants: [],
    participant_entity_ids: [],
    story_arc_id: null,
    foreshadowing_id: null,
    evidence_quote: "",
    certainty: "confirmed",
    created_at: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

function candidate(id: string, description: string): ChronicleCandidate {
  return {
    id,
    novel_id: "novel-1",
    status: "pending",
    title: "候选事件",
    description,
    event_time_text: "第2天",
    sort_order: null,
    participants: ["阿禾"],
    participant_entity_ids: [],
    chapter_id: null,
    story_arc_id: null,
    foreshadowing_id: null,
    evidence_quote: "",
    certainty: "inferred",
    hint: "补一件事",
    model_config_id: null,
    provider_mode: "mock",
    model_name: "模拟模型",
    prompt_version: "chronicle_plan_v1",
    applied: null,
    created_at: "2026-01-02T00:00:00Z",
    reviewed_at: null,
  };
}

describe("ChroniclePanel", () => {
  beforeEach(() => {
    vi.mocked(getChronicle).mockResolvedValue({
      novel_id: "novel-1",
      events: [
        event({ id: "early", description: "入城", event_time_text: "第1天", title: "开城" }),
        event({ id: "late", description: "出城", event_time_text: "第10天" }),
      ],
    });
    vi.mocked(listChronicleCandidates).mockResolvedValue([]);
    vi.mocked(listEntities).mockResolvedValue([]);
    vi.mocked(listStoryArcs).mockResolvedValue([]);
    vi.mocked(listForeshadowing).mockResolvedValue([]);
    vi.mocked(listModelConfigs).mockResolvedValue([]);
  });

  it("shows events in the order the chronicle returns and keeps a plan out until accept", async () => {
    const user = userEvent.setup();
    render(<ChroniclePanel novelId="novel-1" chapters={[{ id: "chapter-1", title: "第一章" }]} />);

    const list = await screen.findByRole("list", { name: "编年史" });
    const items = list.querySelectorAll("li");
    expect(items[0]?.textContent).toContain("第1天");
    expect(items[0]?.textContent).toContain("入城");
    expect(items[1]?.textContent).toContain("第10天");
    expect(items[1]?.textContent).toContain("出城");

    vi.mocked(planChronicle).mockResolvedValue({
      novel_id: "novel-1",
      provider_mode: "mock",
      simulated: true,
      model_config_id: null,
      model_name: "模拟模型",
      prompt_version: "chronicle_plan_v1",
      candidates: [candidate("cand-1", "还没写入")],
      manuscript_changed: false,
      formal_material_changed: false,
      note: "模拟规划，尚未写入正式事件。",
    });
    await user.click(screen.getByRole("button", { name: "生成模拟候选" }));
    expect(planChronicle).toHaveBeenCalledWith("novel-1", { hint: null, use_mock: true });
    expect(await screen.findByText("还没写入")).toBeTruthy();
    expect(screen.getByRole("list", { name: "编年史" }).textContent).not.toContain("还没写入");
    expect(createChronicleEvent).not.toHaveBeenCalled();

    vi.mocked(acceptChronicleCandidate).mockResolvedValue({
      candidate: { ...candidate("cand-1", "还没写入"), status: "accepted" },
      event: event({ id: "written", description: "还没写入", event_time_text: "第2天" }),
      manuscript_changed: false,
      formal_material_changed: true,
    });
    vi.mocked(getChronicle).mockResolvedValue({
      novel_id: "novel-1",
      events: [
        event({ id: "early", description: "入城", event_time_text: "第1天" }),
        event({ id: "written", description: "还没写入", event_time_text: "第2天" }),
        event({ id: "late", description: "出城", event_time_text: "第10天" }),
      ],
    });
    vi.mocked(listChronicleCandidates).mockResolvedValue([]);
    await user.click(screen.getByRole("button", { name: "确认" }));
    expect(acceptChronicleCandidate).toHaveBeenCalledWith("cand-1", undefined);
    expect((await screen.findByRole("list", { name: "编年史" })).textContent).toContain("还没写入");
  });

  it("records a manual event without calling the planner", async () => {
    const user = userEvent.setup();
    vi.mocked(createChronicleEvent).mockResolvedValue(
      event({ id: "manual", description: "亲手记下", event_time_text: "第4天" }),
    );
    render(<ChroniclePanel novelId="novel-1" chapters={[]} />);
    await screen.findByRole("list", { name: "编年史" });
    await user.type(screen.getByRole("textbox", { name: "发生时间" }), "第4天");
    await user.type(screen.getByRole("textbox", { name: "事件描述" }), "亲手记下");
    await user.click(screen.getByRole("button", { name: "记入编年史" }));
    expect(createChronicleEvent).toHaveBeenCalledWith(
      "novel-1",
      expect.objectContaining({ description: "亲手记下", event_time_text: "第4天" }),
    );
    expect(planChronicle).not.toHaveBeenCalled();
    expect(deleteChronicleEvent).not.toHaveBeenCalled();
    expect(rejectChronicleCandidate).not.toHaveBeenCalled();
    expect(deferChronicleCandidate).not.toHaveBeenCalled();
  });

  it("saves an edit onto the formal event", async () => {
    const user = userEvent.setup();
    vi.mocked(updateChronicleEvent).mockResolvedValue(
      event({ id: "early", description: "改过的入城", event_time_text: "第1天", title: "开城" }),
    );
    render(<ChroniclePanel novelId="novel-1" chapters={[{ id: "chapter-1", title: "第一章" }]} />);
    await screen.findByRole("list", { name: "编年史" });
    await user.click(screen.getAllByRole("button", { name: "修改" })[0]);
    const description = screen.getByRole("textbox", { name: "修改事件描述" });
    await user.clear(description);
    await user.type(description, "改过的入城");
    vi.mocked(getChronicle).mockResolvedValue({
      novel_id: "novel-1",
      events: [
        event({ id: "early", description: "改过的入城", event_time_text: "第1天", title: "开城" }),
        event({ id: "late", description: "出城", event_time_text: "第10天" }),
      ],
    });
    await user.click(screen.getByRole("button", { name: "保存修改" }));
    expect(updateChronicleEvent).toHaveBeenCalledWith(
      "early",
      expect.objectContaining({ description: "改过的入城", event_time_text: "第1天" }),
    );
    expect(planChronicle).not.toHaveBeenCalled();
    expect((await screen.findByRole("list", { name: "编年史" })).textContent).toContain("改过的入城");
  });
});
