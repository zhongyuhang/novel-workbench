import { apiRequest } from "./client.ts";

export type ForeshadowingStatus = "open" | "planned" | "resolved" | "abandoned" | "uncertain";
export type ConflictType = "attribute_contradiction" | "negated_fact";
export type Severity = "low" | "medium" | "high";

export type Foreshadowing = {
  id: string;
  novel_id: string;
  introduced_chapter_id: string;
  description: string;
  status: ForeshadowingStatus;
  payoff_chapter_id: string | null;
  evidence_quote: string | null;
  created_at: string;
  updated_at: string;
};

export type ForeshadowingWrite = {
  introduced_chapter_id: string;
  description: string;
  status: ForeshadowingStatus;
  payoff_chapter_id: string | null;
  evidence_quote: string | null;
};

export type ForeshadowingPatch = Partial<ForeshadowingWrite>;

export type SuspectedConflict = {
  conflict_type: ConflictType;
  manuscript_snippet: string;
  confirmed_fact: string;
  source_chapter_id: string;
  source_chapter_title: string;
  source_quote: string;
  severity: Severity;
  confidence: number;
  suggested_action: string;
};

export type ConflictCheck = {
  chapter_id: string;
  novel_id: string;
  provider_mode: "openai_compatible" | "mock";
  prompt_version: string;
  manuscript_changed: false;
  formal_memory_changed: false;
  conflicts: SuspectedConflict[];
  message: string;
};

export type ChapterStat = {
  chapter_id: string;
  title: string;
  volume_id: string | null;
  sort_order: number;
  word_count: number;
};

export type NovelStats = {
  novel_id: string;
  total_word_count: number;
  chapter_count: number;
  target_words: number | null;
  chapters: ChapterStat[];
};

export function listForeshadowing(
  novelId: string,
  status?: ForeshadowingStatus,
  signal?: AbortSignal,
): Promise<Foreshadowing[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiRequest<Foreshadowing[]>(`/api/v1/novels/${novelId}/foreshadowing${query}`, { signal });
}

export function createForeshadowing(
  novelId: string,
  payload: ForeshadowingWrite,
): Promise<Foreshadowing> {
  return apiRequest<Foreshadowing>(`/api/v1/novels/${novelId}/foreshadowing`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateForeshadowing(
  foreshadowingId: string,
  payload: ForeshadowingPatch,
): Promise<Foreshadowing> {
  return apiRequest<Foreshadowing>(`/api/v1/foreshadowing/${foreshadowingId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function checkConflicts(chapterId: string): Promise<ConflictCheck> {
  return apiRequest<ConflictCheck>(`/api/v1/chapters/${chapterId}/conflict-check`, {
    method: "POST",
    body: JSON.stringify({ use_mock: true }),
  });
}

export function getNovelStats(novelId: string, signal?: AbortSignal): Promise<NovelStats> {
  return apiRequest<NovelStats>(`/api/v1/novels/${novelId}/stats`, { signal });
}

export function setWritingGoal(novelId: string, targetWords: number): Promise<NovelStats> {
  return apiRequest<NovelStats>(`/api/v1/novels/${novelId}/writing-goal`, {
    method: "PUT",
    body: JSON.stringify({ target_words: targetWords }),
  });
}
