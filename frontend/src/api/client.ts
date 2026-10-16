import {
  ApiError,
  type ApiErrorBody,
  HealthCheckError,
  type HealthReport,
} from "./types.ts";

const configuredBase = import.meta.env.VITE_API_BASE_URL ?? "";
const SESSION_KEY = "ai-novel-writer.session";

export const SESSION_REQUIRED_EVENT = "ai-novel-writer:session-required";

function notifySessionRequired(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_REQUIRED_EVENT));
  }
}

export function apiUrl(path: string): string {
  const base = configuredBase.replace(/\/$/, "");
  return `${base}${path}`;
}

export const apiDocsUrl = configuredBase
  ? `${configuredBase.replace(/\/$/, "")}/docs`
  : "http://127.0.0.1:8000/docs";

export function readToken(): string | null {
  return sessionStorage.getItem(SESSION_KEY);
}

export function writeToken(token: string): void {
  sessionStorage.setItem(SESSION_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(SESSION_KEY);
}

function isHealthReport(value: unknown): value is HealthReport {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    record.status === "ok" &&
    typeof record.service === "string" &&
    typeof record.version === "string" &&
    record.database === "ok"
  );
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return false;
  }
  const error = (value as { error?: unknown }).error;
  if (typeof error !== "object" || error === null) {
    return false;
  }
  const record = error as Record<string, unknown>;
  return (
    typeof record.code === "string" &&
    typeof record.message === "string" &&
    typeof record.request_id === "string"
  );
}

function toApiError(response: Response, payload: unknown): ApiError {
  if (isErrorBody(payload)) {
    return new ApiError(
      response.status,
      payload.error.code,
      payload.error.message,
      payload.error.request_id,
    );
  }
  return new ApiError(
    response.status,
    "HTTP_ERROR",
    `请求失败（HTTP ${response.status}）。`,
    response.headers.get("X-Request-ID") ?? "",
  );
}

export async function getHealth(signal?: AbortSignal): Promise<HealthReport> {
  let response: Response;
  try {
    response = await fetch(apiUrl("/api/v1/health"), {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new HealthCheckError("无法连接后端服务。请先按 README 启动 API。", null, {
      cause: error,
    });
  }

  if (!response.ok) {
    throw new HealthCheckError(`健康检查未通过（HTTP ${response.status}）。`, response.status);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    throw new HealthCheckError("健康检查返回了无法解析的响应。", response.status, {
      cause: error,
    });
  }

  if (!isHealthReport(payload)) {
    throw new HealthCheckError("健康检查响应格式不符合约定。", response.status);
  }
  return payload;
}

export async function openSession(password: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(apiUrl("/api/v1/auth/session"), {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ password }),
    });
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
    throw toApiError(response, payload);
  }
  if (typeof payload !== "object" || payload === null || !("access_token" in payload)) {
    throw new ApiError(response.status, "INVALID_RESPONSE", "会话响应无法解析。", "");
  }
  const token = (payload as { access_token?: unknown }).access_token;
  if (typeof token !== "string" || token.length === 0) {
    throw new ApiError(response.status, "INVALID_RESPONSE", "会话响应无法解析。", "");
  }
  writeToken(token);
}

let refreshInFlight: Promise<void> | null = null;

function refreshDevSession(): Promise<void> {
  refreshInFlight ??= openSession("").finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function authorizedFetch(path: string, init: RequestInit, allowRetry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = readToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(apiUrl(path), { ...init, headers });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "NETWORK", "无法连接后端服务。", "", { cause: error });
  }

  if (response.status === 401 && allowRetry) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    const error = toApiError(response, payload);
    if (error.code === "UNAUTHENTICATED") {
      clearToken();
      try {
        await refreshDevSession();
      } catch (refreshError) {
        notifySessionRequired();
        throw refreshError;
      }
      return authorizedFetch(path, init, false);
    }
    clearToken();
    notifySessionRequired();
    throw error;
  }
  return response;
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) {
    return null;
  }
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header);
  const value = encoded?.[1];
  if (!value) {
    return null;
  }
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}

export async function apiDownload(
  path: string,
  init: RequestInit = {},
): Promise<{ blob: Blob; filename: string | null }> {
  const response = await authorizedFetch(path, init);
  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    throw toApiError(response, payload);
  }
  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get("Content-Disposition")),
  };
}

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return authorizedFetch(path, init);
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await authorizedFetch(path, init);
  if (response.status === 204) {
    return undefined as T;
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    throw toApiError(response, payload);
  }
  return payload as T;
}
