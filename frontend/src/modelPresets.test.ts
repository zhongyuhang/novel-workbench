import { describe, expect, it } from "vitest";
import type { ProviderPreset } from "./api/models.ts";
import { baseUrlAfterPresetChange, parseHeaderLines } from "./modelPresets.ts";

const presets: ProviderPreset[] = [
  {
    id: "deepseek",
    label: "DeepSeek",
    api_type: "openai_compatible",
    default_base_url: "https://api.deepseek.com/v1",
    hint: "",
  },
  {
    id: "openai",
    label: "OpenAI",
    api_type: "openai_compatible",
    default_base_url: "https://api.openai.com/v1",
    hint: "",
  },
  {
    id: "custom",
    label: "自定义",
    api_type: "openai_compatible",
    default_base_url: "",
    hint: "",
  },
];

describe("baseUrlAfterPresetChange", () => {
  it("fills an empty url from the selected preset", () => {
    const next = presets[0];
    expect(next).toBeDefined();
    if (!next) {
      return;
    }
    expect(baseUrlAfterPresetChange("", "custom", next, presets)).toBe("https://api.deepseek.com/v1");
  });

  it("keeps a base url the author already changed", () => {
    const openai = presets[1];
    expect(openai).toBeDefined();
    if (!openai) {
      return;
    }
    expect(
      baseUrlAfterPresetChange("https://gateway.example/v1", "deepseek", openai, presets),
    ).toBe("https://gateway.example/v1");
  });

  it("replaces a url that still matches the previous preset", () => {
    const openai = presets[1];
    expect(openai).toBeDefined();
    if (!openai) {
      return;
    }
    expect(
      baseUrlAfterPresetChange("https://api.deepseek.com/v1", "deepseek", openai, presets),
    ).toBe("https://api.openai.com/v1");
  });
});

describe("parseHeaderLines", () => {
  it("reads name and value pairs", () => {
    expect(parseHeaderLines("X-Title: novel\n\nX-Trace: abc")).toEqual({
      "X-Title": "novel",
      "X-Trace": "abc",
    });
  });
});
