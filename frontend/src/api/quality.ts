import { apiRequest } from "./client.ts";
import type { Chapter } from "./types.ts";

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
  event_time_text: string | null;
  character_discovered_text: string | null;
  reader_revealed_text: string | null;
  created_at: string;
  updated_at: string;
};

export type ForeshadowingWrite = {
  introduced_chapter_id: string;
  description: string;
  status: ForeshadowingStatus;
  payoff_chapter_id: string | null;
  evidence_quote: string | null;
  event_time_text?: string | null;
  character_discovered_text?: string | null;
  reader_revealed_text?: string | null;
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

export function checkConflicts(chapterId: string, modelConfigId?: string): Promise<ConflictCheck> {
  return apiRequest<ConflictCheck>(`/api/v1/chapters/${chapterId}/conflict-check`, {
    method: "POST",
    body: JSON.stringify(
      modelConfigId ? { use_mock: false, model_config_id: modelConfigId } : { use_mock: true },
    ),
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

export type IssueType =
  | "fact_continuity"
  | "time_continuity"
  | "character_continuity"
  | "foreshadowing"
  | "outline_execution"
  | "text_surface";
export type IssueStatus =
  | "pending"
  | "confirmed"
  | "ignored"
  | "fixed"
  | "expired"
  | "deferred"
  | "intentional";
export type FindingClass = "deterministic" | "suspected" | "creative_risk";
export type EvidenceStatus = "sufficient" | "insufficient";
export type QualityProviderMode = "rule" | "mock" | "openai_compatible";
export type RepairStatus = "proposed" | "accepted" | "rejected" | "conflict";

export type QualityEvidence = {
  kind: string;
  label: string;
  quote: string | null;
  source_chapter_id: string | null;
  source_chapter_title: string;
  source_revision: number | null;
  ref_id: string | null;
};

export type QualityRef = {
  kind: string;
  ref_id: string;
  label: string;
};

export type RepairCandidate = {
  id: string;
  issue_id: string;
  novel_id: string;
  chapter_id: string;
  target_revision: number;
  apply_mode: "replace_selection" | "append";
  applicable: boolean;
  original_snippet: string;
  replacement_text: string;
  rationale: string;
  diff_preview: string;
  provider_mode: QualityProviderMode;
  prompt_version: string;
  status: RepairStatus;
  created_at: string;
  updated_at: string;
};

export type QualityIssue = {
  id: string;
  novel_id: string;
  chapter_id: string;
  chapter_title: string;
  issue_type: IssueType;
  severity: Severity;
  confidence: number;
  status: IssueStatus;
  finding_class: FindingClass;
  manuscript_snippet: string;
  target_revision: number | null;
  location_note: string | null;
  evidence_status: EvidenceStatus;
  evidence: QualityEvidence[];
  related_refs: QualityRef[];
  rule_id: string;
  rule_version: string;
  analysis_version: string | null;
  provider_mode: QualityProviderMode;
  suggested_action: string;
  fixed_revision: number | null;
  recheck_count: number;
  candidates: RepairCandidate[];
  created_at: string;
  updated_at: string;
};

export type QualityCheckResult = {
  novel_id: string;
  chapter_id: string | null;
  provider_mode: QualityProviderMode;
  rule_version: string;
  analysis_version: string | null;
  manuscript_changed: false;
  formal_memory_changed: false;
  issue_count: number;
  expired_count: number;
  reopened_count: number;
  issues: QualityIssue[];
  message: string;
};

export type RepairList = {
  issue_id: string;
  manuscript_changed: false;
  formal_memory_changed: false;
  provider_mode: QualityProviderMode;
  candidates: RepairCandidate[];
  message: string;
};

export type RepairDecision = {
  manuscript_changed: boolean;
  formal_memory_changed: false;
  candidate: RepairCandidate;
  issue: QualityIssue;
  chapter: Chapter | null;
  message: string;
};

export function listQualityIssues(
  novelId: string,
  options?: { status?: IssueStatus; chapterId?: string; includeClosed?: boolean },
  signal?: AbortSignal,
): Promise<QualityIssue[]> {
  const params = new URLSearchParams();
  if (options?.status) {
    params.set("status", options.status);
  }
  if (options?.chapterId) {
    params.set("chapter_id", options.chapterId);
  }
  if (options?.includeClosed) {
    params.set("include_closed", "true");
  }
  const encoded = params.toString();
  const query = encoded === "" ? "" : `?${encoded}`;
  return apiRequest<QualityIssue[]>(`/api/v1/novels/${novelId}/quality-issues${query}`, { signal });
}

export function runQualityCheck(
  novelId: string,
  payload: { chapter_id?: string | null; use_model: boolean; model_config_id?: string | null },
): Promise<QualityCheckResult> {
  return apiRequest<QualityCheckResult>(`/api/v1/novels/${novelId}/quality-check`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateQualityIssue(
  issueId: string,
  status: "pending" | "confirmed" | "ignored" | "deferred" | "intentional",
): Promise<QualityIssue> {
  return apiRequest<QualityIssue>(`/api/v1/quality-issues/${issueId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function generateRepairs(
  issueId: string,
  useModel: boolean,
  modelConfigId?: string | null,
): Promise<RepairList> {
  const body: { use_model: boolean; model_config_id?: string } = { use_model: useModel };
  if (useModel && modelConfigId) {
    body.model_config_id = modelConfigId;
  }
  return apiRequest<RepairList>(`/api/v1/quality-issues/${issueId}/repairs`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function acceptRepair(candidateId: string, targetRevision: number): Promise<RepairDecision> {
  return apiRequest<RepairDecision>(`/api/v1/quality-repairs/${candidateId}/accept`, {
    method: "POST",
    body: JSON.stringify({ target_revision: targetRevision }),
  });
}

export function rejectRepair(candidateId: string): Promise<RepairDecision> {
  return apiRequest<RepairDecision>(`/api/v1/quality-repairs/${candidateId}/reject`, {
    method: "POST",
  });
}
