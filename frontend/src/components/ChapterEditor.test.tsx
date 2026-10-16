import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listChapterVersions, restoreChapter, saveChapter } from "../api/catalog.ts";
import type { Chapter, ChapterVersion } from "../api/types.ts";
import { ApiError } from "../api/types.ts";
import { ChapterEditor } from "./ChapterEditor.tsx";

vi.mock("../api/catalog.ts", () => ({
  saveChapter: vi.fn(),
  getChapter: vi.fn(),
  listChapterVersions: vi.fn(async () => []),
  restoreChapter: vi.fn(),
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
});
