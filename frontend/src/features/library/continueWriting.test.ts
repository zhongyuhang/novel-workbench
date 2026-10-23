import { describe, expect, it } from "vitest";
import type { ChapterSummary, Volume } from "../../api/types.ts";
import {
  latestWritingChapter,
  shellBadge,
  titleForNewChapter,
} from "./continueWriting.ts";

function chapter(partial: Partial<ChapterSummary> & Pick<ChapterSummary, "id" | "title" | "word_count">): ChapterSummary {
  return {
    novel_id: "novel-1",
    volume_id: null,
    sort_order: 0,
    status: "draft",
    revision: 1,
    updated_at: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

describe("continue writing", () => {
  it("opens the latest written chapter and skips empty shells", () => {
    const volumes: Volume[] = [];
    const chapters = [
      chapter({ id: "c18", title: "第18章", word_count: 4707, sort_order: 17 }),
      chapter({ id: "shell", title: "第19章", word_count: 26, sort_order: 18 }),
      chapter({ id: "empty", title: "第20章", word_count: 0, sort_order: 19 }),
    ];

    expect(latestWritingChapter(volumes, chapters)?.id).toBe("c18");
    expect(shellBadge(0)).toBe("未写");
    expect(shellBadge(26)).toBe("过短");
    expect(shellBadge(4707)).toBeNull();
  });

  it("reuses a trailing shell title instead of a stale next-chapter counter", () => {
    const written = Array.from({ length: 18 }, (_item, index) =>
      chapter({
        id: `c${index + 1}`,
        title: `第${index + 1}章`,
        word_count: 4000,
        sort_order: index,
      }),
    );
    expect(titleForNewChapter(written)).toBe("第19章");
    const withShell = [
      ...written,
      chapter({ id: "shell", title: "第19章", word_count: 26, sort_order: 18 }),
    ];
    expect(titleForNewChapter(withShell)).toBe("第19章");
    expect(titleForNewChapter([])).toBe("未命名章节");
  });

  it("keeps going when every chapter is still a shell", () => {
    const only = chapter({ id: "blank", title: "未命名章节", word_count: 0, sort_order: 0 });
    expect(latestWritingChapter([], [only])?.id).toBe("blank");
    expect(latestWritingChapter([], [])).toBeNull();
  });
});