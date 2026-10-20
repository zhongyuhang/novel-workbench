import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  deleteModelConfig,
  listModelConfigs,
  listProviderPresets,
  setDefaultModelConfig,
  testSavedModelConfig,
  updateModelConfig,
} from "../api/models.ts";
import type { ModelConfig } from "../api/types.ts";
import { ModelSettingsPage } from "./ModelSettingsPage.tsx";

vi.mock("../api/models.ts", () => ({
  listModelConfigs: vi.fn(),
  listProviderPresets: vi.fn(),
  createModelConfig: vi.fn(),
  updateModelConfig: vi.fn(),
  deleteModelConfig: vi.fn(),
  testModelConfig: vi.fn(),
  testSavedModelConfig: vi.fn(),
  setDefaultModelConfig: vi.fn(),
}));

const presets = [
  {
    id: "custom",
    label: "自定义",
    api_type: "openai_compatible",
    default_base_url: "",
    hint: "可改地址",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    api_type: "openai_compatible",
    default_base_url: "https://api.deepseek.com/v1",
    hint: "兼容接口",
  },
  {
    id: "openai",
    label: "OpenAI",
    api_type: "openai_compatible",
    default_base_url: "https://api.openai.com/v1",
    hint: "",
  },
];

const saved: ModelConfig = {
  id: "model-1",
  display_name: "主模型",
  provider: "custom",
  provider_type: "openai_compatible",
  base_url: "https://example.invalid/v1",
  model_name: "demo",
  api_key_configured: true,
  api_key_hint: "••••zz99",
  custom_headers_configured: false,
  custom_header_names: [],
  parameters: { timeout_seconds: 60, max_retries: 2, temperature: 0.8, max_output_tokens: 1200 },
  capabilities: { supports_streaming: true },
  is_enabled: true,
  is_default: false,
  last_test_status: "success",
  last_tested_at: "2026-01-01T00:00:00Z",
  last_test_error_code: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("ModelSettingsPage", () => {
  beforeEach(() => {
    vi.mocked(listModelConfigs).mockReset();
    vi.mocked(listProviderPresets).mockReset();
    vi.mocked(listModelConfigs).mockResolvedValue([saved]);
    vi.mocked(listProviderPresets).mockResolvedValue(presets);
    vi.mocked(setDefaultModelConfig).mockResolvedValue({ ...saved, is_default: true });
    vi.mocked(testSavedModelConfig).mockResolvedValue({
      ok: true,
      provider_mode: "openai_compatible",
      message: "连接成功。",
      model_name: "demo",
      elapsed_ms: 12,
      error_code: null,
    });
    vi.mocked(updateModelConfig).mockResolvedValue(saved);
    vi.mocked(deleteModelConfig).mockResolvedValue();
  });

  it("shows test status and can set the tested config as default", async () => {
    const user = userEvent.setup();
    render(<ModelSettingsPage />);
    expect(await screen.findByText("主模型")).toBeTruthy();
    expect(screen.getByText(/状态：成功/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "设为默认" }));
    expect(setDefaultModelConfig).toHaveBeenCalledWith("model-1");
  });

  it("keeps an edited base url when the provider preset changes", async () => {
    const user = userEvent.setup();
    render(<ModelSettingsPage />);
    const url = await screen.findByLabelText("Base URL");
    await user.selectOptions(screen.getByLabelText("服务商"), "deepseek");
    expect((url as HTMLInputElement).value).toBe("https://api.deepseek.com/v1");
    await user.clear(url);
    await user.type(url, "https://gateway.example/v1");
    await user.selectOptions(screen.getByLabelText("服务商"), "openai");
    expect((url as HTMLInputElement).value).toBe("https://gateway.example/v1");
  });
});
