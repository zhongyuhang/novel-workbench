export type HealthReport = {
  status: "ok";
  service: string;
  version: string;
  database: "ok";
};

export class HealthCheckError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "HealthCheckError";
    this.status = status;
  }
}

export type NovelStatus = "draft" | "active" | "archived";
export type ChapterStatus = "outline" | "draft" | "revised" | "final";

export type Novel = {
  id: string;
  title: string;
  genre: string | null;
  synopsis: string | null;
  style_guide: string | null;
  status: NovelStatus;
  created_at: string;
  updated_at: string;
};

export type NovelDraft = {
  title: string;
  genre: string;
  synopsis: string;
  style_guide: string;
  status: NovelStatus;
};

export type Volume = {
  id: string;
  novel_id: string;
  title: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type ChapterSummary = {
  id: string;
  novel_id: string;
  volume_id: string | null;
  title: string;
  sort_order: number;
  word_count: number;
  status: ChapterStatus;
  revision: number;
  updated_at: string;
};

export type TiptapNode = {
  type: string;
  text?: string;
  content?: TiptapNode[];
};

export type TiptapDoc = {
  type: "doc";
  content?: TiptapNode[];
};

export type Chapter = ChapterSummary & {
  content: TiptapDoc;
  content_format: string;
  content_format_version: number;
  created_at: string;
};

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    request_id: string;
  };
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string,
    options?: { cause?: unknown },
  ) {
    super(message, options);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}
