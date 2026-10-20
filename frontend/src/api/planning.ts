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

export type StoryArcType = "main" | "subplot" | "character" | "other";

export const STORY_ARC_TYPE_LABEL: Record<StoryArcType, string> = {
  main: "主线",
  subplot: "支线",
  character: "人物线",
  other: "其他",
};

export type StoryArc = {
  id: string;
  novel_id: string;
  arc_type: StoryArcType;
  title: string;
  summary: string | null;
  sort_order: number;
  status: PlanningStatus;
  revision: number;
  counts_as_fact: boolean;
  created_at: string;
  updated_at: string;
};

export type StoryArcCreate = {
  arc_type: StoryArcType;
  title: string;
  summary?: string | null;
  status?: EditablePlanningStatus | null;
};

export type StoryArcPatch = {
  arc_type?: StoryArcType | null;
  title?: string | null;
  summary?: string | null;
  status?: EditablePlanningStatus | null;
  expected_revision: number;
};

export type VolumeOutline = {
  id: string;
  novel_id: string;
  volume_id: string;
  goal: string | null;
  key_events: string | null;
  start_state: string | null;
  end_state: string | null;
  status: PlanningStatus;
  revision: number;
  counts_as_fact: boolean;
  created_at: string;
  updated_at: string;
};

export type VolumeOutlineView = {
  novel_id: string;
  volume_id: string;
  outline: VolumeOutline | null;
};

export type VolumeOutlineWrite = {
  goal?: string | null;
  key_events?: string | null;
  start_state?: string | null;
  end_state?: string | null;
  status?: EditablePlanningStatus | null;
  expected_revision?: number | null;
};

export type OutlineCandidateScene = {
  goal: string | null;
  conflict: string | null;
  turning_point: string | null;
  expected_outcome: string | null;
  must_convey: string | null;
  must_not_reveal: string | null;
};

export type OutlineCandidatePreview = {
  novel_id: string;
  chapter_id: string;
  provider_mode: "mock" | "openai_compatible";
  simulated: boolean;
  confirmed: false;
  manuscript_changed: false;
  written: false;
  note: string;
  model_config_id?: string | null;
  model_name?: string | null;
  goal: string | null;
  must_advance: string | null;
  required_events: string | null;
  allowed_reveals: string | null;
  forbidden_reveals: string | null;
  target_words: number | null;
  ending_hook: string | null;
  scenes: OutlineCandidateScene[];
};

export type OutlineCandidateAcceptResult = {
  outline: ChapterOutline;
  scenes: SceneCard[];
  manuscript_changed: false;
};

export function listStoryArcs(novelId: string, signal?: AbortSignal): Promise<StoryArc[]> {
  return apiRequest<StoryArc[]>(`/api/v1/novels/${novelId}/story-arcs`, { signal });
}

export function createStoryArc(novelId: string, payload: StoryArcCreate): Promise<StoryArc> {
  return apiRequest<StoryArc>(`/api/v1/novels/${novelId}/story-arcs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateStoryArc(arcId: string, payload: StoryArcPatch): Promise<StoryArc> {
  return apiRequest<StoryArc>(`/api/v1/story-arcs/${arcId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteStoryArc(arcId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/story-arcs/${arcId}`, { method: "DELETE" });
}

export function reorderStoryArcs(novelId: string, arcIds: string[]): Promise<StoryArc[]> {
  return apiRequest<StoryArc[]>(`/api/v1/novels/${novelId}/story-arcs/reorder`, {
    method: "POST",
    body: JSON.stringify({ arc_ids: arcIds }),
  });
}

export function confirmStoryArc(arcId: string, expectedRevision: number): Promise<StoryArc> {
  return apiRequest<StoryArc>(`/api/v1/story-arcs/${arcId}/confirm`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function listVolumeOutlines(
  novelId: string,
  signal?: AbortSignal,
): Promise<VolumeOutline[]> {
  return apiRequest<VolumeOutline[]>(`/api/v1/novels/${novelId}/volume-outlines`, { signal });
}

export function saveVolumeOutline(
  volumeId: string,
  payload: VolumeOutlineWrite,
): Promise<VolumeOutline> {
  return apiRequest<VolumeOutline>(`/api/v1/volumes/${volumeId}/outline`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function confirmVolumeOutline(
  volumeId: string,
  expectedRevision: number,
): Promise<VolumeOutline> {
  return apiRequest<VolumeOutline>(`/api/v1/volumes/${volumeId}/outline/confirm`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision }),
  });
}

export function previewOutlineCandidate(
  chapterId: string,
  modelConfigId?: string,
): Promise<OutlineCandidatePreview> {
  return apiRequest<OutlineCandidatePreview>(`/api/v1/chapters/${chapterId}/outline-candidate`, {
    method: "POST",
    body: JSON.stringify(
      modelConfigId
        ? { use_mock: false, model_config_id: modelConfigId, include_scenes: true }
        : { use_mock: true, include_scenes: true },
    ),
  });
}

export function acceptOutlineCandidate(
  chapterId: string,
  preview: OutlineCandidatePreview,
  expectedRevision: number | undefined,
): Promise<OutlineCandidateAcceptResult> {
  return apiRequest<OutlineCandidateAcceptResult>(
    `/api/v1/chapters/${chapterId}/outline-candidate/accept`,
    {
      method: "POST",
      body: JSON.stringify({
        goal: preview.goal,
        must_advance: preview.must_advance,
        required_events: preview.required_events,
        allowed_reveals: preview.allowed_reveals,
        forbidden_reveals: preview.forbidden_reveals,
        target_words: preview.target_words,
        ending_hook: preview.ending_hook,
        scenes: preview.scenes,
        expected_revision: expectedRevision,
      }),
    },
  );
}
