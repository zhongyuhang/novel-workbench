import { apiRequest } from "./client.ts";

export type EntityType = "character" | "location" | "organization" | "item" | "rule" | "other";
export type EntityStatus = "active" | "inactive" | "unknown";
export type ProposalType =
  | "entity_create"
  | "entity_update"
  | "entity_state"
  | "story_event"
  | "chapter_summary";
export type ProposalStatus = "pending" | "accepted" | "rejected" | "reverted" | "stale";
export type Certainty = "confirmed" | "inferred" | "uncertain";
export type SummaryStatus = "current" | "stale" | "rejected";

export type EntityState = {
  id: string;
  entity_id: string;
  chapter_id: string;
  chapter_title: string;
  source_revision: number | null;
  state_data: Record<string, unknown>;
  evidence_quote: string | null;
  source_type: "manual" | "ai_proposal" | "import";
  valid_from_text: string | null;
  valid_until_text: string | null;
  created_at: string;
};

export type RelationStatus = "active" | "ended" | "unknown";

export type EntityRelation = {
  id: string;
  novel_id: string;
  from_entity_id: string;
  from_entity_name: string;
  to_entity_id: string;
  to_entity_name: string;
  relation_type: string;
  story_time_text: string | null;
  storyline: string | null;
  source_chapter_id: string | null;
  source_chapter_title: string | null;
  source_revision: number | null;
  evidence_quote: string | null;
  status: RelationStatus;
  created_at: string;
  updated_at: string;
};

export type RelationWrite = {
  from_entity_id: string;
  to_entity_id: string;
  relation_type: string;
  story_time_text?: string | null;
  storyline?: string | null;
  source_chapter_id?: string | null;
  source_revision?: number | null;
  evidence_quote?: string | null;
  status?: RelationStatus;
};

export type EntityStateWrite = {
  chapter_id: string;
  state_data: Record<string, unknown>;
  evidence_quote?: string | null;
  valid_from_text?: string | null;
  valid_until_text?: string | null;
};

export type StoryEntity = {
  id: string;
  novel_id: string;
  entity_type: EntityType;
  name: string;
  aliases: string[];
  profile: Record<string, unknown>;
  status: EntityStatus;
  created_at: string;
  updated_at: string;
  states: EntityState[];
};

export type EntityWrite = {
  entity_type: EntityType;
  name: string;
  aliases: string[];
  profile: { summary: string };
  status: EntityStatus;
};

export type MemoryProposal = {
  id: string;
  novel_id: string;
  source_chapter_id: string;
  source_chapter_title: string;
  source_revision: number;
  proposal_type: ProposalType;
  payload: Record<string, unknown>;
  evidence_quote: string;
  certainty: Certainty;
  evidence_in_source: boolean;
  status: ProposalStatus;
  review_note: string | null;
  applied_entity_id: string | null;
  applied_state_id: string | null;
  applied_event_id: string | null;
  applied_summary_id: string | null;
  created_at: string;
  reviewed_at: string | null;
};

export type AnalyzeResult = {
  chapter_id: string;
  novel_id: string;
  source_revision: number;
  status: "completed";
  provider_mode: "mock" | "openai_compatible";
  model_name: string;
  prompt_version: string;
  proposal_count: number;
  proposals: MemoryProposal[];
  message: string;
  formal_memory_changed: false;
  manuscript_changed: false;
};

export type ChapterSummaryRecord = {
  id: string;
  novel_id: string;
  chapter_id: string;
  chapter_title: string;
  summary: string;
  key_facts: string[];
  source_revision: number;
  chapter_revision: number;
  model_name: string | null;
  status: SummaryStatus;
  created_at: string;
  updated_at: string;
};

export type StoryEventRecord = {
  id: string;
  novel_id: string;
  chapter_id: string;
  chapter_title: string;
  source_revision: number | null;
  chapter_revision: number;
  event_time_text: string | null;
  description: string;
  participants: string[];
  evidence_quote: string;
  certainty: Certainty;
  created_at: string;
};

export function listEntities(novelId: string, signal?: AbortSignal): Promise<StoryEntity[]> {
  return apiRequest<StoryEntity[]>(`/api/v1/novels/${novelId}/entities`, { signal });
}

export function createEntity(novelId: string, payload: EntityWrite): Promise<StoryEntity> {
  return apiRequest<StoryEntity>(`/api/v1/novels/${novelId}/entities`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateEntity(entityId: string, payload: Partial<EntityWrite>): Promise<StoryEntity> {
  return apiRequest<StoryEntity>(`/api/v1/entities/${entityId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function listProposals(novelId: string, signal?: AbortSignal): Promise<MemoryProposal[]> {
  return apiRequest<MemoryProposal[]>(`/api/v1/novels/${novelId}/memory-proposals`, { signal });
}

export function listChapterSummaries(
  novelId: string,
  signal?: AbortSignal,
): Promise<ChapterSummaryRecord[]> {
  return apiRequest<ChapterSummaryRecord[]>(`/api/v1/novels/${novelId}/chapter-summaries`, {
    signal,
  });
}

export function listEvents(novelId: string, signal?: AbortSignal): Promise<StoryEventRecord[]> {
  return apiRequest<StoryEventRecord[]>(`/api/v1/novels/${novelId}/events`, { signal });
}

export function listRelations(novelId: string, signal?: AbortSignal): Promise<EntityRelation[]> {
  return apiRequest<EntityRelation[]>(`/api/v1/novels/${novelId}/relations`, { signal });
}

export function createRelation(novelId: string, payload: RelationWrite): Promise<EntityRelation> {
  return apiRequest<EntityRelation>(`/api/v1/novels/${novelId}/relations`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteRelation(relationId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/relations/${relationId}`, { method: "DELETE" });
}

export function createEntityState(entityId: string, payload: EntityStateWrite): Promise<EntityState> {
  return apiRequest<EntityState>(`/api/v1/entities/${entityId}/states`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function analyzeChapter(
  chapterId: string,
  payload: { revision: number; use_mock: boolean; model_config_id?: string },
): Promise<AnalyzeResult> {
  return apiRequest<AnalyzeResult>(`/api/v1/chapters/${chapterId}/analyze`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function acceptProposal(proposalId: string): Promise<MemoryProposal> {
  return apiRequest<MemoryProposal>(`/api/v1/memory-proposals/${proposalId}/accept`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function rejectProposal(proposalId: string): Promise<MemoryProposal> {
  return apiRequest<MemoryProposal>(`/api/v1/memory-proposals/${proposalId}/reject`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function revertProposal(proposalId: string): Promise<MemoryProposal> {
  return apiRequest<MemoryProposal>(`/api/v1/memory-proposals/${proposalId}/revert`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}
