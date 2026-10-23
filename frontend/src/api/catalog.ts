import { apiDownload, apiRequest } from "./client.ts";
import type {
  Chapter,
  ChapterStatus,
  ChapterSummary,
  ChapterVersion,
  ChapterVersionDetail,
  ChapterVersionDiff,
  Novel,
  NovelStatus,
  SaveKind,
  TiptapDoc,
  Volume,
} from "./types.ts";

export type NovelWrite = {
  title: string;
  genre?: string | null;
  synopsis?: string | null;
  style_guide?: string | null;
  core_conflict?: string | null;
  status?: NovelStatus;
};

export function listNovels(signal?: AbortSignal): Promise<Novel[]> {
  return apiRequest<Novel[]>("/api/v1/novels", { signal });
}

export function createNovel(payload: NovelWrite): Promise<Novel> {
  return apiRequest<Novel>("/api/v1/novels", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateNovel(novelId: string, payload: Partial<NovelWrite>): Promise<Novel> {
  return apiRequest<Novel>(`/api/v1/novels/${novelId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteNovel(novelId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/novels/${novelId}`, { method: "DELETE" });
}

export function getNovel(novelId: string, signal?: AbortSignal): Promise<Novel> {
  return apiRequest<Novel>(`/api/v1/novels/${novelId}`, { signal });
}

export function listVolumes(novelId: string, signal?: AbortSignal): Promise<Volume[]> {
  return apiRequest<Volume[]>(`/api/v1/novels/${novelId}/volumes`, { signal });
}

export function createVolume(novelId: string, title: string): Promise<Volume> {
  return apiRequest<Volume>(`/api/v1/novels/${novelId}/volumes`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function updateVolume(volumeId: string, title: string): Promise<Volume> {
  return apiRequest<Volume>(`/api/v1/volumes/${volumeId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function deleteVolume(volumeId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/volumes/${volumeId}`, { method: "DELETE" });
}

export function reorderVolumes(novelId: string, volumeIds: string[]): Promise<Volume[]> {
  return apiRequest<Volume[]>("/api/v1/volumes/reorder", {
    method: "POST",
    body: JSON.stringify({ novel_id: novelId, volume_ids: volumeIds }),
  });
}

export function listChapters(novelId: string, signal?: AbortSignal): Promise<ChapterSummary[]> {
  return apiRequest<ChapterSummary[]>(`/api/v1/novels/${novelId}/chapters`, { signal });
}

export function cleanupShellChapters(novelId: string): Promise<{ deleted: number }> {
  return apiRequest<{ deleted: number }>(`/api/v1/novels/${novelId}/chapters/cleanup-shells`, {
    method: "POST",
  });
}

export function createChapter(
  novelId: string,
  title: string,
  volumeId: string | null,
): Promise<Chapter> {
  return apiRequest<Chapter>(`/api/v1/novels/${novelId}/chapters`, {
    method: "POST",
    body: JSON.stringify({ title, volume_id: volumeId }),
  });
}

export function getChapter(chapterId: string, signal?: AbortSignal): Promise<Chapter> {
  return apiRequest<Chapter>(`/api/v1/chapters/${chapterId}`, { signal });
}

export function saveChapter(
  chapterId: string,
  payload: {
    revision: number;
    content: TiptapDoc;
    title?: string;
    status?: ChapterStatus;
    content_format: "tiptap_json";
    save_kind: SaveKind;
    change_note?: string | null;
  },
): Promise<Chapter> {
  return apiRequest<Chapter>(`/api/v1/chapters/${chapterId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function listChapterVersions(
  chapterId: string,
  signal?: AbortSignal,
): Promise<ChapterVersion[]> {
  return apiRequest<ChapterVersion[]>(`/api/v1/chapters/${chapterId}/versions`, { signal });
}

export function getChapterVersion(
  chapterId: string,
  versionId: string,
  signal?: AbortSignal,
): Promise<ChapterVersionDetail> {
  return apiRequest<ChapterVersionDetail>(
    `/api/v1/chapters/${chapterId}/versions/${versionId}`,
    { signal },
  );
}

export function diffChapterVersions(
  chapterId: string,
  leftId: string,
  rightId: string,
  signal?: AbortSignal,
): Promise<ChapterVersionDiff> {
  const params = new URLSearchParams({ left_id: leftId, right_id: rightId });
  return apiRequest<ChapterVersionDiff>(
    `/api/v1/chapters/${chapterId}/versions/diff?${params.toString()}`,
    { signal },
  );
}

export function restoreChapter(
  chapterId: string,
  payload: { revision: number; version_id: string },
): Promise<Chapter> {
  return apiRequest<Chapter>(`/api/v1/chapters/${chapterId}/restore`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function exportNovel(
  novelId: string,
  format: "markdown" | "txt",
): Promise<{ blob: Blob; filename: string }> {
  const downloaded = await apiDownload(`/api/v1/novels/${novelId}/export`, {
    method: "POST",
    headers: { Accept: "text/markdown, text/plain, application/json" },
    body: JSON.stringify({ format }),
  });
  const extension = format === "markdown" ? "md" : "txt";
  return {
    blob: downloaded.blob,
    filename: downloaded.filename ?? `novel.${extension}`,
  };
}

export function deleteChapter(chapterId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/chapters/${chapterId}`, { method: "DELETE" });
}

export function duplicateChapter(chapterId: string): Promise<Chapter> {
  return apiRequest<Chapter>(`/api/v1/chapters/${chapterId}/duplicate`, { method: "POST" });
}

export function moveChapter(
  chapterId: string,
  volumeId: string | null,
  sortOrder: number,
): Promise<Chapter> {
  return apiRequest<Chapter>(`/api/v1/chapters/${chapterId}/move`, {
    method: "POST",
    body: JSON.stringify({ volume_id: volumeId, sort_order: sortOrder }),
  });
}
