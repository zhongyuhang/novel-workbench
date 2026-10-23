import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  acceptIdeationCandidate,
  answerIdeation,
  createIdeationSession,
  deferIdeationCandidate,
  generateIdeation,
  listIdeationSessions,
  rejectIdeationCandidate,
  type IdeationCandidate,
  type IdeationSession,
} from "../api/ideation.ts";
import { listModelConfigs } from "../api/models.ts";
import { IdeationPanel } from "./IdeationPanel.tsx";

vi.mock("../api/models.ts", () => ({
  listModelConfigs: vi.fn(),
}));

vi.mock("../api/ideation.ts", () => ({
  listIdeationSessions: vi.fn(),
  createIdeationSession: vi.fn(),
  answerIdeation: vi.fn(),
  generateIdeation: vi.fn(),
  acceptIdeationCandidate: vi.fn(),
  rejectIdeationCandidate: vi.fn(),
  deferIdeationCandidate: vi.fn(),
}));

const question = {
  id: "basis",
  prompt: "从哪里开始？",
  help_text: "可以从零开始。",
  optional: false,
  choices: [
    { id: "scratch", label: "从零开始" },
    { id: "existing", label: "顺着已有设定" },
  ],
};

function session(candidates: IdeationCandidate[] = []): IdeationSession {
  return {
    id: "session-1",
    novel_id: "novel-1",
    kind: "guided",
    status: candidates.length > 0 ? "generated" : "collecting",
    step_index: candidates.length > 0 ? 1 : 0,
    answers: [],
    questions: [question],
    current_question: candidates.length > 0 ? null : question,
    ready_to_generate: candidates.length > 0,
    model_config_id: null,
    provider_mode: "mock",
    model_name: "模拟模型",
    prompt_version: "guided_ideation_v1",
    simulated: true,
    candidates,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function candidate(id: string, title: string, genre: string): IdeationCandidate {
  return {
    id,
    session_id: "session-1",
    novel_id: "novel-1",
    candidate_kind: "work_direction",
    title,
    payload: {
      direction: title,
      genre,
      tone: "冷",
      core_conflict: "门外",
      synopsis: "简介",
    },
    status: "pending",
    model_config_id: null,
    model_name: "模拟模型",
    prompt_version: "guided_ideation_v1",
    applied: null,
    created_at: "2026-01-01T00:00:00Z",
    reviewed_at: null,
  };
}

describe("IdeationPanel", () => {
  beforeEach(() => {
    vi.mocked(listModelConfigs).mockResolvedValue([]);
    vi.mocked(listIdeationSessions).mockResolvedValue([]);
    vi.mocked(createIdeationSession).mockReset();
    vi.mocked(answerIdeation).mockReset();
    vi.mocked(generateIdeation).mockReset();
    vi.mocked(acceptIdeationCandidate).mockReset();
    vi.mocked(rejectIdeationCandidate).mockReset();
    vi.mocked(deferIdeationCandidate).mockReset();
  });

  it("starts a mock session and does not accept before the author confirms", async () => {
    const user = userEvent.setup();
    const started = session();
    const ready = {
      ...started,
      step_index: 1,
      current_question: null,
      ready_to_generate: true,
      answers: [{ question_id: "basis", prompt: "从哪里开始？", answer: "scratch" }],
    };
    const first = candidate("cand-1", "候选方向", "寓言");
    const second = candidate("cand-2", "另一条方向", "传奇");
    vi.mocked(createIdeationSession).mockResolvedValue(started);
    vi.mocked(answerIdeation).mockResolvedValue(ready);
    vi.mocked(generateIdeation).mockResolvedValue({
      session: { ...ready, status: "generated", candidates: [first, second] },
      created_candidate_ids: ["cand-1", "cand-2"],
      manuscript_changed: false,
      formal_material_changed: false,
      provider_mode: "mock",
      model_config_id: null,
      model_name: "模拟模型",
      simulated: true,
      note: "模拟候选尚未写入正式资料或正文。",
    });
    vi.mocked(acceptIdeationCandidate).mockImplementation(async (id, payload) => ({
      candidate: {
        ...(id === "cand-1" ? first : second),
        status: "accepted",
        payload: payload ?? first.payload,
      },
      manuscript_changed: false,
      formal_material_changed: true,
    }));
    vi.mocked(rejectIdeationCandidate).mockResolvedValue({
      candidate: { ...second, status: "rejected" },
      manuscript_changed: false,
      formal_material_changed: false,
    });
    vi.mocked(deferIdeationCandidate).mockResolvedValue({
      candidate: { ...first, status: "deferred" },
      manuscript_changed: false,
      formal_material_changed: false,
    });

    const onFormalWrite = vi.fn();
    render(<IdeationPanel novelId="novel-1" onFormalWrite={onFormalWrite} />);
    expect(await screen.findByText("确认之前不会写入题材、文风、人物、世界观或正文。")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "先看模拟候选" }));
    expect(await screen.findByText("从哪里开始？")).toBeTruthy();
    expect(createIdeationSession).toHaveBeenCalledWith("novel-1", {
      kind: "guided",
      use_mock: true,
    });
    expect(acceptIdeationCandidate).not.toHaveBeenCalled();

    await user.click(screen.getByRole("radio", { name: "从零开始" }));
    await user.click(screen.getByRole("button", { name: "下一步" }));
    expect(await screen.findByRole("button", { name: "生成候选" })).toBeTruthy();
    expect(answerIdeation).toHaveBeenCalledWith("session-1", {
      question_id: "basis",
      answer: "scratch",
    });
    await user.click(screen.getByRole("button", { name: "生成候选" }));
    expect(await screen.findByText("模拟候选尚未写入正式资料或正文。")).toBeTruthy();
    expect(generateIdeation).toHaveBeenCalledWith("session-1");

    const firstCard = screen.getByRole("article", { name: "候选方向" });
    await user.click(within(firstCard).getByRole("button", { name: "延后" }));
    expect(await screen.findByText("已延后。正式资料和正文没有改。")).toBeTruthy();
    expect(deferIdeationCandidate).toHaveBeenCalledWith("cand-1");
    expect(acceptIdeationCandidate).not.toHaveBeenCalled();

    const secondCard = screen.getByRole("article", { name: "另一条方向" });
    await user.click(within(secondCard).getByRole("button", { name: "忽略" }));
    expect(await screen.findByText("已忽略。正式资料和正文没有改。")).toBeTruthy();
    expect(rejectIdeationCandidate).toHaveBeenCalledWith("cand-2");

    const currentFirst = screen.getByRole("article", { name: "候选方向" });
    await user.click(within(currentFirst).getByRole("button", { name: "修改后确认" }));
    const genre = within(currentFirst).getByRole("textbox", { name: "题材" });
    await user.clear(genre);
    await user.type(genre, "志怪");
    await user.click(within(currentFirst).getByRole("button", { name: "确认这份修改" }));
    expect(await screen.findByText("已写入。正文没有改。")).toBeTruthy();
    expect(acceptIdeationCandidate).toHaveBeenCalledWith(
      "cand-1",
      expect.objectContaining({ genre: "志怪", direction: "候选方向" }),
    );
    expect(onFormalWrite).toHaveBeenCalledTimes(1);
  });
});
