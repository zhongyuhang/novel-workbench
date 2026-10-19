import { apiDownload, apiRequest, apiUrl, readToken } from "./client.ts";
import { ApiError, type Novel } from "./types.ts";

export type PortableCounts = {
  novels: number;
  volumes: number;
  chapters: number;
  chapter_versions: number;
  story_plans: number;
  chapter_outlines: number;
  scene_cards: number;
  entities: number;
  entity_states: number;
  relations: number;
  events: number;
  summaries: number;
  proposals: number;
  foreshadowing: number;
  writing_goals: number;
  quality_issues: number;
  repair_candidates: number;
  ai_tasks: number;
  model_configs: number;
};

export type PortablePreview = {
  format: string;
  format_version: number;
  novel_title: string;
  can_import: boolean;
  message: string;
  created: PortableCounts;
  skipped: PortableCounts;
  conflicts: PortableCounts;
  invalid: PortableCounts;
  warnings: string[];
  invalid_reasons: string[];
  conflict_map: Record<string, string>;
};

export type PortableImportResult = {
  novel: Novel;
  preview: PortablePreview;
};

export type BackupItem = {
  id: string;
  app_version: string;
  alembic_revision: string;
  created_at: string;
};

export type BackupList = {
  items: BackupItem[];
  latest_success_at: string | null;
};

export async function exportPortable(novelId: string): Promise<{ blob: Blob; filename: string }> {
  const downloaded = await apiDownload(`/api/v1/novels/${novelId}/portable-export`, {
    method: "POST",
  });
  return {
    blob: downloaded.blob,
    filename: downloaded.filename ?? "novel.novelpack.zip",
  };
}

export function listBackups(signal?: AbortSignal): Promise<BackupList> {
  return apiRequest<BackupList>("/api/v1/admin/backups", { signal });
}

export function createBackup(): Promise<BackupItem> {
  return apiRequest<BackupItem>("/api/v1/admin/backups", { method: "POST" });
}

export function previewPortable(file: File): Promise<PortablePreview> {
  return uploadPortable<PortablePreview>("/api/v1/novels/import/preview", file);
}

export function importPortable(file: File): Promise<PortableImportResult> {
  return uploadPortable<PortableImportResult>("/api/v1/novels/import", file);
}

async function uploadPortable<T>(path: string, file: File): Promise<T> {
  const body = new FormData();
  body.append("file", file);
  const headers = new Headers({ Accept: "application/json" });
  const token = readToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  let response: Response;
  try {
    response = await fetch(apiUrl(path), { method: "POST", body, headers });
  } catch (error) {
    throw new ApiError(0, "NETWORK", "无法连接后端服务。", "", { cause: error });
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    if (
      typeof payload === "object" &&
      payload !== null &&
      "error" in payload &&
      typeof payload.error === "object" &&
      payload.error !== null
    ) {
      const error = payload.error as { code?: unknown; message?: unknown; request_id?: unknown };
      if (typeof error.code === "string" && typeof error.message === "string") {
        throw new ApiError(
          response.status,
          error.code,
          error.message,
          typeof error.request_id === "string" ? error.request_id : "",
        );
      }
    }
    throw new ApiError(response.status, "HTTP_ERROR", "作品包没有完成。", "");
  }
  return payload as T;
}
