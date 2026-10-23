import { apiRequest } from "./client.ts";

export type IdeationKind = "guided" | "world" | "character";
export type CandidateKind =
  | "work_direction"
  | "world_setting"
  | "character_card"
  | "character_relation"
  | "character_arc";
export type CandidateStatus = "pending" | "accepted" | "rejected" | "deferred";

export type IdeationChoice = {
  id: string;
  label: string;
};

export type IdeationQuestion = {
  id: string;
  prompt: string;
  help_text: string;
  optional: boolean;
  choices: IdeationChoice[];
};

export type IdeationCandidate = {
  id: string;
  session_id: string;
  novel_id: string;
  candidate_kind: CandidateKind;
  title: string;
  payload: Record<string, unknown>;
  status: CandidateStatus;
  model_config_id: string | null;
  model_name: string;
  prompt_version: string;
  applied: Record<string, unknown> | null;
  created_at: string;
  reviewed_at: string | null;
};

export type IdeationSession = {
  id: string;
  novel_id: string;
  kind: IdeationKind;
  status: "collecting" | "generated";
  step_index: number;
  answers: { question_id: string; prompt: string; answer: string }[];
  questions: IdeationQuestion[];
  current_question: IdeationQuestion | null;
  ready_to_generate: boolean;
  model_config_id: string | null;
  provider_mode: "mock" | "openai_compatible";
  model_name: string;
  prompt_version: string;
  simulated: boolean;
  candidates: IdeationCandidate[];
  created_at: string;
  updated_at: string;
};

export type IdeationGenerateResult = {
  session: IdeationSession;
  created_candidate_ids: string[];
  manuscript_changed: boolean;
  formal_material_changed: boolean;
  provider_mode: "mock" | "openai_compatible";
  model_config_id: string | null;
  model_name: string;
  simulated: boolean;
  note: string;
};

export type IdeationDecision = {
  candidate: IdeationCandidate;
  manuscript_changed: boolean;
  formal_material_changed: boolean;
};

export function listIdeationSessions(
  novelId: string,
  signal?: AbortSignal,
): Promise<IdeationSession[]> {
  return apiRequest<IdeationSession[]>(`/api/v1/novels/${novelId}/ideation/sessions`, { signal });
}

export function createIdeationSession(
  novelId: string,
  payload: { kind: IdeationKind; use_mock: boolean; model_config_id?: string },
): Promise<IdeationSession> {
  return apiRequest<IdeationSession>(`/api/v1/novels/${novelId}/ideation/sessions`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function answerIdeation(
  sessionId: string,
  payload: { question_id: string; answer: string },
): Promise<IdeationSession> {
  return apiRequest<IdeationSession>(`/api/v1/ideation/sessions/${sessionId}/answers`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function generateIdeation(sessionId: string): Promise<IdeationGenerateResult> {
  return apiRequest<IdeationGenerateResult>(`/api/v1/ideation/sessions/${sessionId}/generate`, {
    method: "POST",
  });
}

export function acceptIdeationCandidate(
  candidateId: string,
  payload?: Record<string, unknown>,
): Promise<IdeationDecision> {
  return apiRequest<IdeationDecision>(`/api/v1/ideation-candidates/${candidateId}/accept`, {
    method: "POST",
    body: JSON.stringify(payload ? { payload } : {}),
  });
}

export function rejectIdeationCandidate(candidateId: string): Promise<IdeationDecision> {
  return apiRequest<IdeationDecision>(`/api/v1/ideation-candidates/${candidateId}/reject`, {
    method: "POST",
  });
}

export function deferIdeationCandidate(candidateId: string): Promise<IdeationDecision> {
  return apiRequest<IdeationDecision>(`/api/v1/ideation-candidates/${candidateId}/defer`, {
    method: "POST",
  });
}
