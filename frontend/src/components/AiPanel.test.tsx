import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { acceptAiTask, createAiTask, rejectAiTask, streamAiTask } from "../api/ai.ts";
import { listModelConfigs } from "../api/models.ts";
import type { Chapter, ModelConfig } from "../api/types.ts";
import { AiPanel } from "./AiPanel.tsx";

vi.mock("../api/models.ts", () => ({
  listModelConfigs: vi.fn(),
}));

vi.mock("../api/ai.ts", () => ({
  createAiTask: vi.fn(),
  streamAiTask: vi.fn(),
  cancelAiTask: vi.fn(),
  acceptAiTask: vi.fn(),
  rejectAiTask: vi.fn(),
}));

const chapter: Chapter = {
  id: "chapter-1",
  novel_id: "novel-1",
  volume_id: null,
  title: "开篇",
  sort_order: 0,
  word_count: 4,
  status: "draft",
  revision: 2,
  updated_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  content_format: "tiptap_json",
  content_format_version: 1,
  content: {
    type: "doc",
    content: [{ type: "paragraph", content: [{ type: "text", text: "原有正文" }] }],
  },
};

const model: ModelConfig = {
  id: "model-1",
  display_name: "主模型",
  provider_type: "openai_compatible",
  base_url: "https://example.invalid/v1",
  model_name: "demo",
  api_key_configured: true,
  api_key_hint: "••••abcd",
  parameters: {},
  capabilities: {},
  is_enabled: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderPanel(onAccepted = vi.fn()) {
  return render(
    <AiPanel
      novelId="novel-1"
      chapter={chapter}
      savedRevision={2}
      selectionText="原有正文"
      editorDirty={false}
      onAccepted={onAccepted}
    />,
  );
}

describe("AiPanel", () => {
  beforeEach(() => {
    vi.mocked(listModelConfigs).mockReset();
    vi.mocked(createAiTask).mockReset();
    vi.mocked(streamAiTask).mockReset();
    vi.mocked(acceptAiTask).mockReset();
    vi.mocked(rejectAiTask).mockReset();
  });

  it("t006 shows configuration guidance and does not start a task", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([]);
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "续写" }));

    expect(await screen.findByText(/请先到模型设置/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "打开模型设置" }).getAttribute("href")).toBe("#/settings");
    expect(createAiTask).not.toHaveBeenCalled();
  });

  it("accepts a mock candidate without treating it as already saved", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([model]);
    vi.mocked(createAiTask).mockResolvedValue({
      id: "task-1",
      novel_id: "novel-1",
      chapter_id: chapter.id,
      task_type: "continue",
      status: "queued",
      model_config_id: null,
      provider_mode: "mock",
      model_name: "mock",
      prompt_version: "m3.v1",
      output_text: null,
      error_code: null,
      error_message_safe: null,
      input_tokens: null,
      output_tokens: null,
      resolution: null,
      started_at: null,
      finished_at: null,
      created_at: "2026-01-01T00:00:00Z",
    });
    vi.mocked(streamAiTask).mockImplementation(async (_taskId, onEvent) => {
      onEvent({ event: "token", data: { text: "候选" } });
      onEvent({
        event: "task.completed",
        data: { output_text: "候选", provider_mode: "mock" },
      });
    });
    const saved = { ...chapter, revision: 3, word_count: 6 };
    vi.mocked(acceptAiTask).mockResolvedValue({
      task: {
        id: "task-1",
        novel_id: "novel-1",
        chapter_id: chapter.id,
        task_type: "continue",
        status: "completed",
        model_config_id: null,
        provider_mode: "mock",
        model_name: "mock",
        prompt_version: "m3.v1",
        output_text: "候选",
        error_code: null,
        error_message_safe: null,
        input_tokens: 1,
        output_tokens: 1,
        resolution: "accepted",
        started_at: null,
        finished_at: null,
        created_at: "2026-01-01T00:00:00Z",
      },
      chapter: saved,
    });
    const onAccepted = vi.fn();
    const user = userEvent.setup();
    renderPanel(onAccepted);

    await user.click(await screen.findByRole("button", { name: "用模拟模型试运行" }));

    expect(await screen.findByText("模拟输出")).toBeTruthy();
    expect(screen.getByLabelText("候选文本").textContent).toContain("候选");
    await user.click(screen.getByRole("button", { name: "采纳" }));

    expect(acceptAiTask).toHaveBeenCalledWith("task-1", {
      target_revision: 2,
      apply_mode: "append",
    });
    expect(onAccepted).toHaveBeenCalledWith(saved);
  });

  it("reject leaves the accept callback unused", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([model]);
    vi.mocked(createAiTask).mockResolvedValue({
      id: "task-2",
      novel_id: "novel-1",
      chapter_id: chapter.id,
      task_type: "continue",
      status: "queued",
      model_config_id: model.id,
      provider_mode: "openai_compatible",
      model_name: "demo",
      prompt_version: "m3.v1",
      output_text: null,
      error_code: null,
      error_message_safe: null,
      input_tokens: null,
      output_tokens: null,
      resolution: null,
      started_at: null,
      finished_at: null,
      created_at: "2026-01-01T00:00:00Z",
    });
    vi.mocked(streamAiTask).mockImplementation(async (_taskId, onEvent) => {
      onEvent({ event: "task.completed", data: { output_text: "不要写入", provider_mode: "openai_compatible" } });
    });
    vi.mocked(rejectAiTask).mockResolvedValue({
      id: "task-2",
      novel_id: "novel-1",
      chapter_id: chapter.id,
      task_type: "continue",
      status: "completed",
      model_config_id: model.id,
      provider_mode: "openai_compatible",
      model_name: "demo",
      prompt_version: "m3.v1",
      output_text: "不要写入",
      error_code: null,
      error_message_safe: null,
      input_tokens: null,
      output_tokens: null,
      resolution: "rejected",
      started_at: null,
      finished_at: null,
      created_at: "2026-01-01T00:00:00Z",
    });
    const onAccepted = vi.fn();
    const user = userEvent.setup();
    renderPanel(onAccepted);

    await user.click(await screen.findByRole("button", { name: "续写" }));
    await user.click(await screen.findByRole("button", { name: "放弃" }));

    expect(rejectAiTask).toHaveBeenCalledWith("task-2");
    expect(onAccepted).not.toHaveBeenCalled();
    expect(await screen.findByText(/正文没有改动/)).toBeTruthy();
  });

  it("rewrites the current selection and compares before accept", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([model]);
    vi.mocked(createAiTask).mockResolvedValue({
      id: "task-rewrite",
      novel_id: "novel-1",
      chapter_id: chapter.id,
      task_type: "rewrite",
      status: "queued",
      model_config_id: null,
      provider_mode: "mock",
      model_name: "mock",
      prompt_version: "rewrite_selection_v1",
      output_text: null,
      error_code: null,
      error_message_safe: null,
      input_tokens: null,
      output_tokens: null,
      resolution: null,
      started_at: null,
      finished_at: null,
      created_at: "2026-01-01T00:00:00Z",
    });
    vi.mocked(streamAiTask).mockImplementation(async (_taskId, onEvent) => {
      onEvent({
        event: "task.completed",
        data: { output_text: "改写后的句子", provider_mode: "mock" },
      });
    });
    vi.mocked(acceptAiTask).mockResolvedValue({
      task: {
        id: "task-rewrite",
        novel_id: "novel-1",
        chapter_id: chapter.id,
        task_type: "rewrite",
        status: "completed",
        model_config_id: null,
        provider_mode: "mock",
        model_name: "mock",
        prompt_version: "rewrite_selection_v1",
        output_text: "改写后的句子",
        error_code: null,
        error_message_safe: null,
        input_tokens: 1,
        output_tokens: 1,
        resolution: "accepted",
        started_at: null,
        finished_at: null,
        created_at: "2026-01-01T00:00:00Z",
      },
      chapter: { ...chapter, revision: 3 },
    });
    const user = userEvent.setup();
    renderPanel();

    expect(screen.getByLabelText("当前选区").textContent).toContain("原有正文");
    await user.click(await screen.findByRole("button", { name: "用模拟模型改写选区" }));

    expect(createAiTask).toHaveBeenCalledWith(
      expect.objectContaining({
        task_type: "rewrite",
        selection_text: "原有正文",
        use_mock: true,
      }),
    );
    const compare = await screen.findByLabelText("选区对比");
    expect(compare.textContent).toContain("原有正文");
    expect(compare.textContent).toContain("改写后的句子");
    await user.click(screen.getByRole("button", { name: "采纳" }));
    expect(acceptAiTask).toHaveBeenCalledWith("task-rewrite", {
      target_revision: 2,
      apply_mode: "replace_selection",
    });
  });
});
