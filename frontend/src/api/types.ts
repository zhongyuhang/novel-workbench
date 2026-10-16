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

export type TiptapMark = {
  type: string;
  attrs?: Record<string, unknown>;
};

export type TiptapNode = {
  type: string;
  text?: string;
  attrs?: Record<string, unknown>;
  marks?: TiptapMark[];
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

export type SaveKind = "manual" | "autosave";
export type ChangeSource = "manual" | "ai_accepted" | "restore" | "import";

export type ChapterVersion = {
  id: string;
  chapter_id: string;
  revision: number;
  content_format: string;
  content_format_version: number;
  change_source: ChangeSource;
  change_note: string | null;
  word_count: number;
  preview: string;
  created_at: string;
};

export type ApiErrorBody = {
  error: {
    code: string;
    message: string;
    request_id: string;
  };
};

export type ProviderType = "openai_compatible" | "mock";
export type ProviderMode = "openai_compatible" | "mock";
export type AiTaskType = "continue" | "rewrite" | "polish" | "expand" | "shrink" | "proofread";
export type AiTaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type ApplyMode = "append" | "insert" | "replace_selection";

export type ModelConfig = {
  id: string;
  display_name: string;
  provider_type: ProviderType;
  base_url: string;
  model_name: string;
  api_key_configured: boolean;
  api_key_hint: string | null;
  parameters: Record<string, unknown>;
  capabilities: Record<string, unknown>;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type ModelConfigInput = {
  display_name: string;
  provider_type: ProviderType;
  base_url: string;
  model_name: string;
  api_key?: string;
  timeout_seconds: number;
  max_retries: number;
  temperature: number | null;
  max_output_tokens: number | null;
  supports_streaming: boolean;
  supports_json_output: boolean;
  is_enabled: boolean;
};

export type AiTask = {
  id: string;
  novel_id: string;
  chapter_id: string | null;
  task_type: AiTaskType;
  status: AiTaskStatus;
  model_config_id: string | null;
  provider_mode: ProviderMode;
  model_name: string;
  prompt_version: string;
  output_text: string | null;
  error_code: string | null;
  error_message_safe: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  resolution: "accepted" | "rejected" | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

export type AiTaskCreateInput = {
  novel_id: string;
  chapter_id: string;
  task_type: AiTaskType;
  instruction: string;
  selection_text?: string;
  target_revision: number;
  model_config_id?: string;
  constraints?: {
    max_words?: number;
    must_include?: string;
    must_avoid?: string;
  };
  use_mock?: boolean;
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
