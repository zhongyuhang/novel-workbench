import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listChapters, listNovels, listVolumes } from "../api/catalog.ts";
import { getHealth } from "../api/client.ts";
import { listBackups } from "../api/portable.ts";
import type { ChapterSummary, Novel } from "../api/types.ts";
import { NovelLibraryPage } from "./NovelLibraryPage.tsx";

vi.mock("../api/client.ts", async () => {
  const actual = await vi.importActual<typeof import("../api/client.ts")>("../api/client.ts");
  return {
    ...actual,
    getHealth: vi.fn(async () => ({
      status: "ok",
      service: "api",
      version: "1.0.0",
      database: "ok",
    })),
  };
});

vi.mock("../api/catalog.ts", () => ({
  createNovel: vi.fn(),
  deleteNovel: vi.fn(),
  listChapters: vi.fn(),
  listNovels: vi.fn(),
  listVolumes: vi.fn(),
  updateNovel: vi.fn(),
}));

vi.mock("../api/portable.ts", () => ({
  createBackup: vi.fn(),
  importPortable: vi.fn(),
  listBackups: vi.fn(async () => ({ latest_success_at: null, items: [] })),
  previewPortable: vi.fn(),
}));

const novel: Novel = {
  id: "novel-1",
  title: "长河夜行",
  genre: null,
  synopsis: null,
  style_guide: null,
  core_conflict: null,
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-02T00:00:00Z",
};

function chapter(id: string, title: string, wordCount: number, sortOrder: number): ChapterSummary {
  return {
    id,
    novel_id: novel.id,
    volume_id: null,
    title,
    sort_order: sortOrder,
    word_count: wordCount,
    status: "draft",
    revision: 1,
    updated_at: "2026-01-02T00:00:00Z",
  };
}

describe("NovelLibraryPage", () => {
  beforeEach(() => {
    vi.mocked(getHealth).mockClear();
    vi.mocked(listNovels).mockResolvedValue([novel]);
    vi.mocked(listBackups).mockResolvedValue({ latest_success_at: null, items: [] });
    vi.mocked(listVolumes).mockResolvedValue([]);
    vi.mocked(listChapters).mockResolvedValue([
      chapter("full", "第18章", 4707, 17),
      chapter("shell", "第19章", 26, 18),
    ]);
    window.location.hash = "#/";
  });

  it("continues into the latest written chapter and skips empty shells", async () => {
    const user = userEvent.setup();
    render(<NovelLibraryPage />);

    await user.click(await screen.findByRole("button", { name: "继续写" }));

    expect(window.location.hash).toBe("#/novels/novel-1/chapters/full");
    expect(listChapters).toHaveBeenCalledWith("novel-1");
  });
});
