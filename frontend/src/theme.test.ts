import { describe, expect, it } from "vitest";
import { resolveTheme } from "./theme.ts";

describe("resolveTheme", () => {
  it("follows the system until the author overrides it", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});
