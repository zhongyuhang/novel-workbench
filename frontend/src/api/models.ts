import { apiRequest } from "./client.ts";
import type { ModelConfig, ModelConfigInput, ProviderType } from "./types.ts";

export type ProviderPreset = {
  id: string;
  label: string;
  api_type: string;
  default_base_url: string;
  hint: string;
};

export type ModelTestResult = {
  ok: boolean;
  provider_mode: "mock" | "openai_compatible";
  message: string;
  model_name: string | null;
  elapsed_ms: number | null;
  error_code: string | null;
};

export function listModelConfigs(signal?: AbortSignal): Promise<ModelConfig[]> {
  return apiRequest<ModelConfig[]>("/api/v1/settings/models", { signal });
}

export function listProviderPresets(signal?: AbortSignal): Promise<ProviderPreset[]> {
  return apiRequest<ProviderPreset[]>("/api/v1/settings/models/presets", { signal });
}

export function createModelConfig(payload: ModelConfigInput): Promise<ModelConfig> {
  return apiRequest<ModelConfig>("/api/v1/settings/models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateModelConfig(
  configId: string,
  payload: Partial<ModelConfigInput>,
): Promise<ModelConfig> {
  return apiRequest<ModelConfig>(`/api/v1/settings/models/${configId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteModelConfig(configId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/settings/models/${configId}`, { method: "DELETE" });
}

export function testModelConfig(payload: {
  config_id?: string;
  provider_type?: ProviderType;
  base_url?: string;
  model_name?: string;
  api_key?: string;
  timeout_seconds?: number;
}): Promise<ModelTestResult> {
  return apiRequest("/api/v1/settings/models/test", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function testSavedModelConfig(configId: string): Promise<ModelTestResult> {
  return apiRequest(`/api/v1/settings/models/${configId}/test`, { method: "POST" });
}

export function setDefaultModelConfig(configId: string): Promise<ModelConfig> {
  return apiRequest(`/api/v1/settings/models/${configId}/default`, { method: "PUT" });
}
