import { apiRequest } from "./client.ts";
import type { Certainty, StoryEventRecord } from "./memory.ts";

export type ChronicleCandidateStatus = "pending" | "accepted" | "rejected" | "deferred";

export type ChronicleView = {
  novel_id: string;
  events: StoryEventRecord[];
};

export type ChronicleEventWrite = {
  title?: string | null;
  description: string;
  event_time_text?: string | null;
  participants?: string[];
  participant_entity_ids?: string[];
  chapter_id?: string | null;
  story_arc_id?: string | null;
  foreshadowing_id?: string | null;
  evidence_quote?: string | null;
  certainty?: Certainty;
  sort_order?: number | null;
};

export type ChronicleCandidate = {
  id: string;
  novel_id: string;
  status: ChronicleCandidateStatus;
  title: string | null;
  description: string;
  event_time_text: string | null;
  sort_order: number | null;
  participants: string[];
  participant_entity_ids: string[];
  chapter_id: string | null;
  story_arc_id: string | null;
  foreshadowing_id: string | null;
  evidence_quote: string;
  certainty: Certainty;
  hint: string | null;
  model_config_id: string | null;
  provider_mode: "mock" | "openai_compatible";
  model_name: string;
  prompt_version: string;
  applied: Record<string, unknown> | null;
  created_at: string;
  reviewed_at: string | null;
};

export type ChroniclePlanResult = {
  novel_id: string;
  provider_mode: "mock" | "openai_compatible";
  simulated: boolean;
  model_config_id: string | null;
  model_name: string;
  prompt_version: string;
  candidates: ChronicleCandidate[];
  manuscript_changed: false;
  formal_material_changed: false;
  note: string;
};

export type ChronicleDecision = {
  candidate: ChronicleCandidate;
  event: StoryEventRecord | null;
  manuscript_changed: false;
  formal_material_changed: boolean;
};

export function getChronicle(novelId: string, signal?: AbortSignal): Promise<ChronicleView> {
  return apiRequest<ChronicleView>(`/api/v1/novels/${novelId}/chronicle`, { signal });
}

export function createChronicleEvent(
  novelId: string,
  payload: ChronicleEventWrite,
): Promise<StoryEventRecord> {
  return apiRequest<StoryEventRecord>(`/api/v1/novels/${novelId}/events`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateChronicleEvent(
  eventId: string,
  payload: Partial<ChronicleEventWrite>,
): Promise<StoryEventRecord> {
  return apiRequest<StoryEventRecord>(`/api/v1/events/${eventId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteChronicleEvent(eventId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/events/${eventId}`, { method: "DELETE" });
}

export function listChronicleCandidates(
  novelId: string,
  signal?: AbortSignal,
): Promise<ChronicleCandidate[]> {
  return apiRequest<ChronicleCandidate[]>(`/api/v1/novels/${novelId}/chronicle/candidates`, {
    signal,
  });
}

export function planChronicle(
  novelId: string,
  payload: { hint?: string | null; model_config_id?: string | null; use_mock?: boolean },
): Promise<ChroniclePlanResult> {
  return apiRequest<ChroniclePlanResult>(`/api/v1/novels/${novelId}/chronicle/plan`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function acceptChronicleCandidate(
  candidateId: string,
  event?: ChronicleEventWrite,
): Promise<ChronicleDecision> {
  return apiRequest<ChronicleDecision>(`/api/v1/chronicle-candidates/${candidateId}/accept`, {
    method: "POST",
    body: JSON.stringify(event ? { event } : {}),
  });
}

export function rejectChronicleCandidate(candidateId: string): Promise<ChronicleDecision> {
  return apiRequest<ChronicleDecision>(`/api/v1/chronicle-candidates/${candidateId}/reject`, {
    method: "POST",
  });
}

export function deferChronicleCandidate(candidateId: string): Promise<ChronicleDecision> {
  return apiRequest<ChronicleDecision>(`/api/v1/chronicle-candidates/${candidateId}/defer`, {
    method: "POST",
  });
}
