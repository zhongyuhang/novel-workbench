import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  diffChapterVersions,
  getChapter,
  getChapterVersion,
  listChapterVersions,
  restoreChapter,
  saveChapter,
} from "../api/catalog.ts";
import type { Chapter, ChapterVersion } from "../api/types.ts";
import { ApiError } from "../api/types.ts";
import { ChapterEditor } from "./ChapterEditor.tsx";

vi.mock("../api/catalog.ts", () => ({
  saveChapter: vi.fn(),
  getChapter: vi.fn(),
  listChapterVersions: vi.fn(async () => []),
  restoreChapter: vi.fn(),
  getChapterVersion: vi.fn(),
  diffChapterVersions: vi.fn(),
}));

const chapter: Chapter = {
  id: "chapter-1",
  novel_id: "novel-1",
  volume_id: null,
  title: "开篇",
  sort_order: 0,
  word_count: 8,
  status: "draft",
  revision: 1,
  updated_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  content_format: "tiptap_json",
  content_format_version: 1,
  content: {
    type: "doc",
    content: [{ type: "paragraph", content: [{ type: "text", text: "编辑器里的原句" }] }],
  },
};

const storedVersion: ChapterVersion = {
  id: "version-1",
  chapter_id: chapter.id,
  revision: 2,
  content_format: "tiptap_json",
  content_format_version: 1,
  change_source: "manual",
  change_note: null,
  word_count: 8,
  preview: "编辑器里的原句",
  created_at: "2026-01-02T00:00:00Z",
};

describe("ChapterEditor", () => {
  beforeEach(() => {
    vi.mocked(saveChapter).mockReset();
    vi.mocked(restoreChapter).mockReset();
    vi.mocked(listChapterVersions).mockReset();
    vi.mocked(listChapterVersions).mockResolvedValue([]);
  });

  it("t003 keeps editor text and shows retry when autosave fails", async () => {
    vi.mocked(saveChapter).mockRejectedValue(
      new ApiError(0, "NETWORK", "无法连接后端服务。", ""),
    );
    render(
      <ChapterEditor
        chapter={chapter}
        autosaveDelayMs={20}
        onSaved={() => {}}
        onUnsavedChange={() => {}}
      />,
    );

    expect((await screen.findByRole("textbox", { name: "正文" })).textContent).toContain(
      "编辑器里的原句",
    );
    await new Promise((resolve) => {
      setTimeout(resolve, 80);
    });
    expect(saveChapter).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("章节标题"), { target: { value: "新的标题" } });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("自动保存失败");
    expect(alert.textContent).toContain("正文仍留在编辑器里");
    expect(alert.textContent).toContain("无法连接后端服务。");
    expect(screen.getByRole("textbox", { name: "正文" }).textContent).toContain("编辑器里的原句");
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
    expect(saveChapter).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(saveChapter).mock.calls[0]?.[1];
    expect(payload?.save_kind).toBe("autosave");
    expect(payload?.title).toBe("新的标题");
    expect(JSON.stringify(payload?.content)).toContain("编辑器里的原句");

    vi.mocked(saveChapter).mockResolvedValue({
      ...chapter,
      title: "新的标题",
      revision: 2,
    });
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("已自动保存。")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "正文" }).textContent).toContain("编辑器里的原句");
    expect((screen.getByLabelText("章节标题") as HTMLInputElement).value).toBe("新的标题");
  });

  it("asks before restoring a version", async () => {
    vi.mocked(listChapterVersions).mockResolvedValue([storedVersion]);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(
      <ChapterEditor chapter={chapter} onSaved={() => {}} onUnsavedChange={() => {}} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "恢复修订 2" }));
    expect(confirm).toHaveBeenCalled();
    expect(restoreChapter).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "正文" }).textContent).toContain("编辑器里的原句");
  });

  it("keeps the local draft and compares it when autosave conflicts", async () => {
    vi.mocked(saveChapter).mockRejectedValueOnce(
      new ApiError(409, "REVISION_CONFLICT", "章节已在其他操作中更新，请刷新并比较差异。", "req"),
    );
    vi.mocked(getChapter).mockResolvedValue({
      ...chapter,
      revision: 4,
      content: {
        type: "doc",
        content: [{ type: "paragraph", content: [{ type: "text", text: "服务器正文" }] }],
      },
    });
    render(
      <ChapterEditor
        chapter={chapter}
        autosaveDelayMs={20}
        onSaved={() => {}}
        onUnsavedChange={() => {}}
      />,
    );
    fireEvent.change(screen.getByLabelText("章节标题"), { target: { value: "本地标题" } });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("本地草稿还在编辑器里");
    expect(alert.textContent).toContain("不会写成版本快照");
    expect((await screen.findAllByText("服务器正文")).length).toBeGreaterThan(0);
    expect(screen.getByRole("textbox", { name: "正文" }).textContent).toContain("编辑器里的原句");
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();
    expect((screen.getByLabelText("章节标题") as HTMLInputElement).value).toBe("本地标题");

    vi.mocked(saveChapter).mockResolvedValue({
      ...chapter,
      title: "本地标题",
      revision: 5,
    });
    fireEvent.click(screen.getByRole("button", { name: "用本地草稿手动保存" }));
    await screen.findByText("已用本地草稿手动保存，并留下版本快照。自动保存本身不产生快照。");
    const payload = vi.mocked(saveChapter).mock.calls.at(-1)?.[1];
    expect(payload?.save_kind).toBe("manual");
    expect(payload?.revision).toBe(4);
    expect(payload?.title).toBe("本地标题");
  });

  it("puts title, status, and sync on one line and hides formatting until text is selected", async () => {
    render(<ChapterEditor chapter={chapter} onSaved={() => {}} onUnsavedChange={() => {}} />);

    expect(screen.queryByRole("toolbar", { name: "正文格式" })).toBeNull();
    const status = await screen.findByRole("status", { name: "章节状态" });
    expect(status.textContent).toContain("已同步");
    expect(status.textContent).toContain("修订号 1");
    expect(status.textContent).toContain("字");
    expect(screen.getByLabelText("章节标题")).toBeTruthy();
    expect(screen.getByLabelText("状态")).toBeTruthy();
    expect(status.closest(".editor-meta-line")).toBeTruthy();
  });

  it("previews a version diff before restore", async () => {
    const older = { ...storedVersion, id: "version-old", revision: 2, preview: "旧句子" };
    const newer = {
      ...storedVersion,
      id: "version-new",
      revision: 3,
      preview: "新句子",
      change_source: "ai_accepted" as const,
      ai_task_id: "task-9",
    };
    vi.mocked(listChapterVersions).mockResolvedValue([newer, older]);
    vi.mocked(getChapterVersion).mockResolvedValue({
      ...older,
      text: "旧句子全文",
      memory_proposal_ids: ["proposal-1"],
    });
    vi.mocked(diffChapterVersions).mockResolvedValue({
      left: {
        id: older.id,
        revision: 2,
        change_source: "manual",
        change_note: null,
        created_at: older.created_at,
        word_count: 3,
        label: "修订 2",
        ai_task_id: null,
        repair_candidate_id: null,
        memory_proposal_ids: [],
      },
      right: {
        id: null,
        revision: 1,
        change_source: null,
        change_note: null,
        created_at: chapter.updated_at,
        word_count: 8,
        label: "当前正文",
        ai_task_id: null,
        repair_candidate_id: null,
        memory_proposal_ids: [],
      },
      hunks: [
        { op: "delete", text: "旧句子全文" },
        { op: "insert", text: "编辑器里的原句" },
      ],
    });
    render(<ChapterEditor chapter={chapter} onSaved={() => {}} onUnsavedChange={() => {}} />);

    expect(await screen.findByText(/来源：AI 任务 task-9/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "预览修订 2" }));
    expect((await screen.findAllByText("旧句子全文")).length).toBeGreaterThan(0);
    expect(screen.getByText(/记忆分析提案：proposal-1/)).toBeTruthy();
    expect(screen.getByText("编辑器里的原句", { selector: ".diff-insert" })).toBeTruthy();
    expect(restoreChapter).not.toHaveBeenCalled();
  });
});
