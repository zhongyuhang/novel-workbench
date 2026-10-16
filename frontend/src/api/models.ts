import { apiRequest } from "./client.ts";
import type { ModelConfig, ModelConfigInput } from "./types.ts";

export function listModelConfigs(signal?: AbortSignal): Promise<ModelConfig[]> {
  return apiRequest<ModelConfig[]>("/api/v1/settings/models", { signal });
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
  provider_type?: ModelConfigInput["provider_type"];
  base_url?: string;
  model_name?: string;
  api_key?: string;
  timeout_seconds?: number;
}): Promise<{ ok: boolean; provider_mode: "mock" | "openai_compatible"; message: string }> {
  return apiRequest("/api/v1/settings/models/test", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
