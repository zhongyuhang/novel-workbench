import { apiFetch, apiRequest } from "./client.ts";
import type { StreamEvent, StreamEventName } from "../features/ai/candidateStream.ts";
import { ApiError } from "./types.ts";
import type {
  AiTask,
  AiTaskCreateInput,
  ApplyMode,
  Chapter,
  CompiledContext,
} from "./types.ts";

export function compileContext(payload: {
  novel_id: string;
  chapter_id?: string;
  task_type: AiTaskCreateInput["task_type"];
  instruction: string;
  selection_text?: string;
  target_revision?: number;
  constraints?: AiTaskCreateInput["constraints"];
  context_budget?: number;
  pinned_include?: string[];
  pinned_exclude?: string[];
}): Promise<CompiledContext> {
  return apiRequest<CompiledContext>("/api/v1/ai/tasks/context/compile", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getTaskContext(taskId: string): Promise<CompiledContext> {
  return apiRequest<CompiledContext>(`/api/v1/ai/tasks/${taskId}/context`);
}

export function createAiTask(payload: AiTaskCreateInput): Promise<AiTask> {
  return apiRequest<AiTask>("/api/v1/ai/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAiTask(taskId: string, signal?: AbortSignal): Promise<AiTask> {
  return apiRequest<AiTask>(`/api/v1/ai/tasks/${taskId}`, { signal });
}

export function cancelAiTask(taskId: string): Promise<AiTask> {
  return apiRequest<AiTask>(`/api/v1/ai/tasks/${taskId}/cancel`, { method: "POST" });
}

export function acceptAiTask(
  taskId: string,
  payload: { target_revision: number; apply_mode: ApplyMode },
): Promise<{ task: AiTask; chapter: Chapter }> {
  return apiRequest(`/api/v1/ai/tasks/${taskId}/accept`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function rejectAiTask(taskId: string): Promise<AiTask> {
  return apiRequest<AiTask>(`/api/v1/ai/tasks/${taskId}/reject`, { method: "POST" });
}

export async function streamAiTask(
  taskId: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiFetch(`/api/v1/ai/tasks/${taskId}/events`, {
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok || response.body === null) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (typeof payload === "object" && payload !== null && "error" in payload) {
      const error = (payload as { error?: { code?: unknown; message?: unknown; request_id?: unknown } }).error;
      if (
        error &&
        typeof error.code === "string" &&
        typeof error.message === "string" &&
        typeof error.request_id === "string"
      ) {
        throw new ApiError(response.status, error.code, error.message, error.request_id);
      }
    }
    throw new ApiError(response.status, "HTTP_ERROR", "无法读取生成进度。", "");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) {
      break;
    }
    buffer += decoder.decode(chunk.value, { stream: true });
    let splitAt = buffer.indexOf("\n\n");
    while (splitAt >= 0) {
      const frame = buffer.slice(0, splitAt);
      buffer = buffer.slice(splitAt + 2);
      const event = parseSseFrame(frame);
      if (event) {
        onEvent(event);
      }
      splitAt = buffer.indexOf("\n\n");
    }
  }
}

function parseSseFrame(frame: string): StreamEvent | null {
  let eventName = "";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      data = line.slice("data:".length).trim();
    }
  }
  if (!isEventName(eventName) || data === "") {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(data);
    if (typeof parsed !== "object" || parsed === null) {
      return null;
    }
    return { event: eventName, data: parsed as StreamEvent["data"] };
  } catch {
    return null;
  }
}

function isEventName(value: string): value is StreamEventName {
  return (
    value === "task.started" ||
    value === "token" ||
    value === "task.completed" ||
    value === "task.failed" ||
    value === "task.cancelled" ||
    value === "heartbeat"
  );
}
