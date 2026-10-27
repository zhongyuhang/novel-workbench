import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ThemeSwitcher } from "./components/ThemeSwitcher.tsx";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "index.css"), "utf8");

describe("rainbow island theme", () => {
  it("keeps the three preference keys and labels dark as 彩虹", () => {
    localStorage.clear();
    render(<ThemeSwitcher />);
    expect(screen.getByRole("group", { name: "颜色模式" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "系统" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "浅色" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "彩虹" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("button", { name: "赛博" })).toBeNull();
  });

  it("paints dark mode with rainbow island tokens and freezes motion when requested", () => {
    expect(css).toContain("--canvas: #1a1230");
    expect(css).toContain("--surface: #261b3d");
    expect(css).toContain("--surface-raised: #342652");
    expect(css).toContain("--text-primary: #f7f2ff");
    expect(css).toContain("--text-muted: #b5a8d0");
    expect(css).toContain("#ef476f");
    expect(css).toContain("#ffd166");
    expect(css).toContain("#06d6a0");
    expect(css).toContain("#3f88c5");
    expect(css).toContain("#5438dc");
    expect(css).toContain("prefers-reduced-motion: reduce");
    expect(css).toContain("animation: none !important");
    expect(css).not.toContain("clip-path");
    expect(css).not.toContain("#fcee0a");
    expect(css).not.toContain("#00f0ff");
    expect(css).not.toContain("hue-rotate");
    expect(css).not.toContain("赛博");
  });
});
