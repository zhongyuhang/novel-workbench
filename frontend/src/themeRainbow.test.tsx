import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ThemeSwitcher } from "./components/ThemeSwitcher.tsx";

declare const process: { cwd(): string };

async function readThemeCss(): Promise<string> {
  const specifier = "node:fs";
  const filesystem = (await import(specifier)) as {
    readFileSync(path: string, encoding: "utf8"): string;
  };
  return filesystem.readFileSync(`${process.cwd()}/src/index.css`, "utf8");
}

describe("SONORA HUD theme", () => {
  it("keeps the three preference keys and labels dark as 赛博", () => {
    localStorage.clear();
    render(<ThemeSwitcher />);
    expect(screen.getByRole("group", { name: "颜色模式" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "系统" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "浅色" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByRole("button", { name: "赛博" }).getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByRole("button", { name: "彩虹" })).toBeNull();
  });

  it("paints dark mode with SONORA tokens and freezes motion when requested", async () => {
    const css = await readThemeCss();
    expect(css).toContain('--canvas: #07050c');
    expect(css).toContain('--surface: #0c0814');
    expect(css).toContain('--surface-raised: #110b1b');
    expect(css).toContain('--text-primary: #f7eff6');
    expect(css).toContain('--text-muted: #9a8ca6');
    expect(css).toContain('#ff2ea6');
    expect(css).toContain('#ff67c5');
    expect(css).toContain('#ffc1e4');
    expect(css).toContain('#15f4ff');
    expect(css).toContain('#eaff4a');
    expect(css).toContain('rgba(255, 46, 166, 0.2)');
    expect(css).toContain('cubic-bezier(0.16, 1, 0.3, 1)');
    expect(css).toContain('hud-scan');
    expect(css).toContain('hud-wipe');
    expect(css).toContain('font-size: 18px');
    expect(css).toContain('line-height: 1.7');
    expect(css).toContain('var(--font-reading)');
    expect(css).toContain('prefers-reduced-motion: reduce');
    expect(css).toContain('animation: none !important');
    expect(css).not.toContain('#1a1230');
    expect(css).not.toContain('#ef476f');
    expect(css).not.toContain('#ffd166');
    expect(css).not.toContain('#06d6a0');
    expect(css).not.toContain('#3f88c5');
    expect(css).not.toContain('#5438dc');
    expect(css).not.toContain('conic-gradient');
    expect(css).not.toContain('clip-path');
    expect(css).not.toContain('hue-rotate');
    expect(css).not.toContain('#fcee0a');
    expect(css).not.toContain('#00f0ff');
    expect(css).not.toContain('彩虹');
  });
});
