import type { ProviderPreset } from "./api/models.ts";

export function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

/** Keep a Base URL the author already changed. Preset defaults only fill an untouched field. */
export function baseUrlAfterPresetChange(
  currentUrl: string,
  previousPresetId: string,
  nextPreset: ProviderPreset,
  presets: readonly ProviderPreset[],
): string {
  const previous = presets.find((item) => item.id === previousPresetId);
  const previousDefault = normalizeBaseUrl(previous?.default_base_url ?? "");
  const current = normalizeBaseUrl(currentUrl);
  if (current === "" || current === previousDefault) {
    return nextPreset.default_base_url;
  }
  return currentUrl;
}

export function parseHeaderLines(text: string): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (trimmed === "") {
      continue;
    }
    const index = trimmed.indexOf(":");
    if (index <= 0) {
      throw new Error("每一行要写成 Header名: 值");
    }
    const name = trimmed.slice(0, index).trim();
    const value = trimmed.slice(index + 1).trim();
    if (name === "" || value === "") {
      throw new Error("每一行要写成 Header名: 值");
    }
    headers[name] = value;
  }
  return headers;
}

export function formatHeaderLines(names: readonly string[]): string {
  return names.map((name) => `${name}: `).join("\n");
}
