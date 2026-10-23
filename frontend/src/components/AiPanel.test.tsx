import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { acceptAiTask, cancelAiTask, compileContext, createAiTask, getAiTask, getTaskContext, rejectAiTask, streamAiTask } from "../api/ai.ts";
import { ApiError } from "../api/types.ts";
import type { AiTask } from "../api/types.ts";
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
  compileContext: vi.fn(),
  getTaskContext: vi.fn(),
  getAiTask: vi.fn(),
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
  provider: "custom",
  provider_type: "openai_compatible",
  base_url: "https://example.invalid/v1",
  model_name: "demo",
  api_key_configured: true,
  api_key_hint: "••••abcd",
  custom_headers_configured: false,
  custom_header_names: [],
  parameters: {},
  capabilities: {},
  is_enabled: true,
  is_default: true,
  last_test_status: "success",
  last_tested_at: "2026-01-01T00:00:00Z",
  last_test_error_code: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function taskFixture(
  id: string,
  status: AiTask["status"],
  output: string | null,
): AiTask {
  return {
    id,
    novel_id: "novel-1",
    chapter_id: chapter.id,
    task_type: "continue",
    status,
    model_config_id: null,
    provider_mode: "mock",
    model_name: "mock",
    prompt_version: "m3.v1",
    output_text: output,
    error_code: null,
    error_message_safe: status === "failed" ? "模型请求超时。正文没有被修改。" : null,
    input_tokens: null,
    output_tokens: null,
    resolution: null,
    started_at: null,
    finished_at: null,
    created_at: "2026-01-01T00:00:00Z",
  };
}

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
    vi.mocked(compileContext).mockReset();
    vi.mocked(getTaskContext).mockReset();
    vi.mocked(cancelAiTask).mockReset();
    vi.mocked(getAiTask).mockReset();
    vi.mocked(getAiTask).mockImplementation(async (id: string) => taskFixture(id, "completed", "候选"));
    vi.mocked(getTaskContext).mockResolvedValue({
      task_type: "continue",
      novel_id: "novel-1",
      chapter_id: chapter.id,
      target_revision: 2,
      items: [],
      total_token_estimate: 0,
      budget: 0,
      warnings: ["当时只保存了整段提示，没有条目级来源。"],
      compiler_version: "",
      context_hash: "",
      legacy: true,
    });
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

  it("shows a timeout fragment and accepts it on the same path", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([model]);
    vi.mocked(createAiTask).mockResolvedValue({
      id: "task-partial",
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
      onEvent({ event: "token", data: { text: "已写出" } });
      onEvent({
        event: "task.completed",
        data: {
          output_text: "已写出一段",
          partial: true,
          error_message: "模型超时，已保留已生成的片段。正文还没改，可以采纳这段候选。",
          provider_mode: "openai_compatible",
        },
      });
    });
    const saved = { ...chapter, revision: 3, word_count: 8 };
    vi.mocked(acceptAiTask).mockResolvedValue({
      task: {
        id: "task-partial",
        novel_id: "novel-1",
        chapter_id: chapter.id,
        task_type: "continue",
        status: "completed",
        model_config_id: model.id,
        provider_mode: "openai_compatible",
        model_name: "demo",
        prompt_version: "m3.v1",
        output_text: "已写出一段",
        error_code: "MODEL_TIMEOUT",
        error_message_safe: "模型超时，已保留已生成的片段。正文还没改，可以采纳这段候选。",
        partial: true,
        input_tokens: 1,
        output_tokens: 2,
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

    await user.click(await screen.findByRole("button", { name: "续写" }));

    expect(await screen.findByText(/可以采纳这段候选/)).toBeTruthy();
    expect(screen.getByLabelText("候选文本").textContent).toContain("已写出一段");
    await user.click(screen.getByRole("button", { name: "采纳" }));

    expect(acceptAiTask).toHaveBeenCalledWith("task-partial", {
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

    await user.click(await screen.findByRole("button", { name: "选择改写" }));
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

  it("pins context material and sends it with the next task", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([model]);
    const preview = {
      task_type: "continue",
      novel_id: "novel-1",
      chapter_id: chapter.id,
      target_revision: 2,
      items: [
        {
          id: "hard-rule",
          kind: "hard_rule",
          content: "作品硬规则：短句",
          source_type: "novel",
          source_id: "novel-1",
          source_revision: null,
          certainty: "confirmed",
          priority: 1,
          token_estimate: 9,
          included: true,
          exclusion_reason: null,
          hit_reason: "作品硬规则",
          warnings: [],
        },
        {
          id: "outline:draft",
          kind: "chapter_outline",
          content: "未确认章节大纲（不是事实）：草稿目标",
          source_type: "chapter_outline",
          source_id: "draft",
          source_revision: 1,
          certainty: "draft",
          priority: 2,
          token_estimate: 12,
          included: false,
          exclusion_reason: "草稿不能当作事实",
          hit_reason: "章节大纲未确认",
          warnings: [],
        },
      ],
      total_token_estimate: 9,
      budget: 6000,
      warnings: ["预算还有余量"],
      compiler_version: "e2.v1",
      context_hash: "abc",
      legacy: false,
    };
    vi.mocked(compileContext).mockResolvedValue(preview);
    vi.mocked(createAiTask).mockResolvedValue({
      id: "task-context",
      novel_id: "novel-1",
      chapter_id: chapter.id,
      task_type: "continue",
      status: "queued",
      model_config_id: null,
      provider_mode: "mock",
      model_name: "mock",
      prompt_version: "m4.v1",
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
    vi.mocked(streamAiTask).mockResolvedValue();
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "查看本次上下文" }));

    expect((await screen.findAllByText(/作品硬规则：短句/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/草稿不能当作事实/)).toBeTruthy();
    expect(screen.getByText(/预算还有余量/)).toBeTruthy();
    const includeButtons = screen.getAllByRole("button", { name: "固定纳入" });
    await user.click(includeButtons[1]);
    await user.click(screen.getByRole("button", { name: "重新编译" }));

    expect(compileContext).toHaveBeenLastCalledWith(
      expect.objectContaining({ pinned_include: ["outline:draft"], pinned_exclude: [] }),
    );

    await user.click(screen.getByRole("button", { name: "用模拟模型试运行" }));
    expect(createAiTask).toHaveBeenCalledWith(
      expect.objectContaining({
        use_mock: true,
        pinned_include: ["outline:draft"],
        pinned_exclude: [],
      }),
    );
  });

  it("reads the saved candidate when the event stream drops", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([model]);
    vi.mocked(createAiTask).mockResolvedValue(taskFixture("task-drop", "queued", null));
    vi.mocked(streamAiTask).mockRejectedValue(new Error("stream closed"));
    vi.mocked(getAiTask).mockResolvedValue(taskFixture("task-drop", "completed", "服务器上的候选"));
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "用模拟模型试运行" }));

    expect(await screen.findByLabelText("候选文本")).toHaveProperty("textContent", expect.stringContaining("服务器上的候选"));
    expect(screen.queryByText("stream closed")).toBeNull();
    expect(getAiTask).toHaveBeenCalledWith("task-drop");
  });

  it("switches verbs and keeps model constraints inside more settings", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([model]);
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByRole("button", { name: "选择续写" })).toHaveProperty("ariaPressed", "true");
    expect(screen.getByRole("textbox", { name: "接着写什么" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "选择润色" })?.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByText("更多设置").closest("details")?.open).toBe(false);

    await user.click(screen.getByRole("button", { name: "选择润色" }));

    expect(screen.getByRole("button", { name: "选择润色" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("textbox", { name: "润色要求" })).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "接着写什么" })).toBeNull();
    expect(screen.getByRole("button", { name: "润色" })).toBeTruthy();

    await user.click(screen.getByText("更多设置"));
    expect(screen.getByText("更多设置").closest("details")?.open).toBe(true);
    expect(screen.getByLabelText("模型")).toBeTruthy();
    expect(screen.getByLabelText("必须包含")).toBeTruthy();
    expect(screen.getByLabelText("不要出现")).toBeTruthy();
  });

  it("saves an instruction locally and previews the request", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([model]);
    localStorage.removeItem("novel-workbench-instructions");
    const user = userEvent.setup();
    renderPanel();

    await user.type(await screen.findByRole("textbox", { name: "接着写什么" }), "雨声再近一点");
    expect(screen.getByLabelText("Prompt 预览").textContent).toContain("动作：续写");
    expect(screen.getByLabelText("Prompt 预览").textContent).toContain("雨声再近一点");
    expect(screen.getByLabelText("Prompt 预览").textContent).toContain("仅本章");

    await user.click(screen.getByRole("button", { name: "存为我的指令" }));
    expect(await screen.findByText(/已存为我的指令/)).toBeTruthy();
    expect(JSON.parse(localStorage.getItem("novel-workbench-instructions") ?? "[]")).toEqual(["雨声再近一点"]);

    await user.click(screen.getByRole("button", { name: "+大纲" }));
    expect(screen.getByRole("button", { name: "+大纲" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "仅本章" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByLabelText("Prompt 预览").textContent).toContain("本章 + 大纲");
  });

  it("shows the stored candidate when cancel arrives after the task already finished", async () => {
    vi.mocked(listModelConfigs).mockResolvedValue([model]);
    vi.mocked(createAiTask).mockResolvedValue(taskFixture("task-late", "queued", null));
    let releaseStream = () => {};
    const streamHeld = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });
    vi.mocked(streamAiTask).mockImplementation(async (_taskId, onEvent) => {
      onEvent({ event: "token", data: { text: "甲" } });
      await streamHeld;
    });
    vi.mocked(cancelAiTask).mockRejectedValue(new ApiError(409, "TASK_STATE", "任务已经结束，不能再取消。", "req-1"));
    vi.mocked(getAiTask).mockResolvedValue(taskFixture("task-late", "completed", "甲乙"));
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "用模拟模型试运行" }));
    await user.click(await screen.findByRole("button", { name: "取消" }));

    expect(await screen.findByText("任务已经结束，不能再取消。")).toBeTruthy();
    expect(screen.getByLabelText("候选文本").textContent).toContain("甲乙");
    expect(screen.queryByText("已取消。正文没有被改写。")).toBeNull();
    releaseStream();
  });
});
