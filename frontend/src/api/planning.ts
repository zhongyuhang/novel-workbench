import { apiRequest } from "./client.ts";

export type PlanningStatus = "draft" | "confirmed" | "stale" | "archived";
export type EditablePlanningStatus = "draft" | "stale" | "archived";

export type StoryPlan = {
  id: string;
  novel_id: string;
  logline: string | null;
  body: string | null;
  ending_intent: string | null;
  status: PlanningStatus;
  revision: number;
  counts_as_fact: boolean;
  created_at: string;
  updated_at: string;
};

export type StoryPlanView = {
  novel_id: string;
  plan: StoryPlan | null;
};

export type StoryPlanWrite = {
  logline?: string | null;
  body?: string | null;
  ending_intent?: string | null;
  status?: EditablePlanningStatus | null;
  expected_revision?: number | null;
};

export type ChapterOutline = {
  id: string;
  novel_id: string;
  chapter_id: string;
  goal: string | null;
  must_advance: string | null;
  required_events: string | null;
  allowed_reveals: string | null;
  forbidden_reveals: string | null;
  target_words: number | null;
  ending_hook: string | null;
  status: PlanningStatus;
  revision: number;
  counts_as_fact: boolean;
  created_at: string;
  updated_at: string;
};

export type ChapterOutlineView = {
  novel_id: string;
  chapter_id: string;
  outline: ChapterOutline | null;
};

export type ChapterOutlineWrite = {
  goal?: string | null;
  must_advance?: string | null;
  required_events?: string | null;
  allowed_reveals?: string | null;
  forbidden_reveals?: string | null;
  target_words?: number | null;
  ending_hook?: string | null;
  status?: EditablePlanningStatus | null;
  expected_revision?: number | null;
};

export type EntityRef = {
  id: string;
  name: string | null;
  entity_type: string | null;
  available: boolean;
};

export type SceneCard = {
  id: string;
  novel_id: string;
  chapter_id: string;
  sort_order: number;
  goal: string | null;
  location_entity_id: string | null;
  location: EntityRef | null;
  character_entity_ids: string[];
  characters: EntityRef[];
  conflict: string | null;
  turning_point: string | null;
  expected_outcome: string | null;
  must_convey: string | null;
  must_not_reveal: string | null;
  status: PlanningStatus;
  revision: number;
  counts_as_fact: boolean;
  created_at: string;
  updated_at: string;
};

export type SceneCardWrite = {
  goal?: string | null;
  location_entity_id?: string | null;
  character_entity_ids?: string[];
  conflict?: string | null;
  turning_point?: string | null;
  expected_outcome?: string | null;
  must_convey?: string | null;
  must_not_reveal?: string | null;
  status?: PlanningStatus;
  expected_revision?: number;
};

export const PLANNING_STATUS_LABEL: Record<PlanningStatus, string> = {
  draft: "草稿",
  confirmed: "已确认",
  stale: "待复核",
  archived: "已归档",
};

export function planningFactNote(countsAsFact: boolean): string {
  return countsAsFact
    ? "已确认。之后才会当作创作约束。"
    : "未确认，不会当作强制事实。";
}

export function getStoryPlan(novelId: string, signal?: AbortSignal): Promise<StoryPlanView> {
  return apiRequest<StoryPlanView>(`/api/v1/novels/${novelId}/story-plan`, { signal });
}

export function saveStoryPlan(novelId: string, payload: StoryPlanWrite): Promise<StoryPlan> {
  return apiRequest<StoryPlan>(`/api/v1/novels/${novelId}/story-plan`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function confirmStoryPlan(novelId: string, expectedRevision: number): Promise<StoryPlan> {
  return apiRequest<StoryPlan>(`/api/v1/novels/${novelId}/story-plan/confirm`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function listChapterOutlines(
  novelId: string,
  signal?: AbortSignal,
): Promise<ChapterOutline[]> {
  return apiRequest<ChapterOutline[]>(`/api/v1/novels/${novelId}/chapter-outlines`, { signal });
}

export function getChapterOutline(
  chapterId: string,
  signal?: AbortSignal,
): Promise<ChapterOutlineView> {
  return apiRequest<ChapterOutlineView>(`/api/v1/chapters/${chapterId}/outline`, { signal });
}

export function saveChapterOutline(
  chapterId: string,
  payload: ChapterOutlineWrite,
): Promise<ChapterOutline> {
  return apiRequest<ChapterOutline>(`/api/v1/chapters/${chapterId}/outline`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function confirmChapterOutline(
  chapterId: string,
  expectedRevision: number,
): Promise<ChapterOutline> {
  return apiRequest<ChapterOutline>(`/api/v1/chapters/${chapterId}/outline/confirm`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function listScenes(chapterId: string, signal?: AbortSignal): Promise<SceneCard[]> {
  return apiRequest<SceneCard[]>(`/api/v1/chapters/${chapterId}/scenes`, { signal });
}

export function createScene(chapterId: string, payload: SceneCardWrite): Promise<SceneCard> {
  return apiRequest<SceneCard>(`/api/v1/chapters/${chapterId}/scenes`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateScene(sceneId: string, payload: SceneCardWrite): Promise<SceneCard> {
  return apiRequest<SceneCard>(`/api/v1/scenes/${sceneId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteScene(sceneId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/scenes/${sceneId}`, { method: "DELETE" });
}

export function reorderScenes(chapterId: string, sceneIds: string[]): Promise<SceneCard[]> {
  return apiRequest<SceneCard[]>(`/api/v1/chapters/${chapterId}/scenes/reorder`, {
    method: "POST",
    body: JSON.stringify({ scene_ids: sceneIds }),
  });
}
