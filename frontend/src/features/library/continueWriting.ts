import type { ChapterSummary, Volume } from "../../api/types.ts";

/** Same bound as the server: a bridge sentence is still an empty shell. */
export const SHELL_WORD_LIMIT = 40;

const NUMBERED = /^第\s*([0-9]{1,4})\s*章$/;

export function isShellChapter(wordCount: number): boolean {
  return wordCount <= SHELL_WORD_LIMIT;
}

export function chapterNumber(title: string): number | null {
  const match = NUMBERED.exec(title.trim());
  if (!match?.[1]) {
    return null;
  }
  return Number(match[1]);
}

export function shellBadge(wordCount: number): "未写" | "过短" | null {
  if (!isShellChapter(wordCount)) {
    return null;
  }
  return wordCount === 0 ? "未写" : "过短";
}

export function nextNumberedTitle(titles: string[]): string {
  let highest = 0;
  let numbered = false;
  for (const title of titles) {
    const number = chapterNumber(title);
    if (number === null) {
      continue;
    }
    numbered = true;
    highest = Math.max(highest, number);
  }
  if (!numbered) {
    return "未命名章节";
  }
  return `第${Math.max(highest, titles.length) + 1}章`;
}

/** Recompute the title from the server chapter list. A trailing shell is reused by name. */
export function titleForNewChapter(chapters: Array<Pick<ChapterSummary, "title" | "word_count">>): string {
  if (chapters.length === 0) {
    return "未命名章节";
  }
  const last = chapters[chapters.length - 1];
  if (last && isShellChapter(last.word_count) && last.title.trim()) {
    return last.title.trim();
  }
  if (chapters.some((chapter) => chapterNumber(chapter.title) !== null)) {
    return nextNumberedTitle(chapters.map((chapter) => chapter.title));
  }
  return "未命名章节";
}

export function readingOrder(volumes: Volume[], chapters: ChapterSummary[]): ChapterSummary[] {
  const volumeOrder = new Map(volumes.map((volume) => [volume.id, volume.sort_order]));
  return [...chapters].sort((left, right) => {
    const leftVolume = left.volume_id === null ? -1 : (volumeOrder.get(left.volume_id) ?? 0);
    const rightVolume = right.volume_id === null ? -1 : (volumeOrder.get(right.volume_id) ?? 0);
    if (leftVolume !== rightVolume) {
      return leftVolume - rightVolume;
    }
    if (left.sort_order !== right.sort_order) {
      return left.sort_order - right.sort_order;
    }
    if (left.id < right.id) {
      return -1;
    }
    if (left.id > right.id) {
      return 1;
    }
    return 0;
  });
}

/** Latest chapter that has real text. Empty shells at the tail are skipped. */
export function latestWritingChapter(
  volumes: Volume[],
  chapters: ChapterSummary[],
): ChapterSummary | null {
  const ordered = readingOrder(volumes, chapters);
  for (let index = ordered.length - 1; index >= 0; index -= 1) {
    const chapter = ordered[index];
    if (chapter && !isShellChapter(chapter.word_count)) {
      return chapter;
    }
  }
  return ordered.at(-1) ?? null;
}
