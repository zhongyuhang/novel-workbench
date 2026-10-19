import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PortablePreview } from "../api/portable.ts";
import { LibraryMaintenance } from "./LibraryMaintenance.tsx";

const preview: PortablePreview = {
  format: "ai-novel-writer-portable-v1",
  format_version: 1,
  novel_title: "可携带的城",
  can_import: true,
  message: "可以导入为新作品，不会覆盖已有作品。",
  created: emptyCounts({ chapters: 2, novels: 1 }),
  skipped: emptyCounts({ model_configs: 1 }),
  conflicts: emptyCounts({ novels: 1, chapters: 2 }),
  invalid: emptyCounts(),
  warnings: ["模型 API Key 和访问口令不会导入。"],
  invalid_reasons: [],
  conflict_map: {},
};

describe("LibraryMaintenance", () => {
  it("shows when there has not been a successful backup", () => {
    render(
      <LibraryMaintenance
        latestSuccessAt={null}
        backupPending={false}
        onBackup={vi.fn()}
        preview={null}
        previewError=""
        importPending={false}
        onChooseFile={vi.fn()}
        onConfirmImport={vi.fn()}
        onCancelPreview={vi.fn()}
      />,
    );

    expect(screen.getByText(/还没有成功的整库备份/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "立即备份" })).toBeTruthy();
  });

  it("shows the latest successful backup time and confirms a new import", async () => {
    const onBackup = vi.fn();
    const onConfirmImport = vi.fn();
    const user = userEvent.setup();
    render(
      <LibraryMaintenance
        latestSuccessAt="2026-10-19T02:30:00Z"
        backupPending={false}
        onBackup={onBackup}
        preview={preview}
        previewError=""
        importPending={false}
        onChooseFile={vi.fn()}
        onConfirmImport={onConfirmImport}
        onCancelPreview={vi.fn()}
      />,
    );

    expect(screen.getByText(/最近一次成功备份/)).toBeTruthy();
    expect(screen.getByText(/不会覆盖现有作品/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "立即备份" }));
    await user.click(screen.getByRole("button", { name: "导入为新作品" }));
    expect(onBackup).toHaveBeenCalledOnce();
    expect(onConfirmImport).toHaveBeenCalledOnce();
  });

  it("shows an unsupported package error and does not offer a failing import", () => {
    render(
      <LibraryMaintenance
        latestSuccessAt={null}
        backupPending={false}
        onBackup={vi.fn()}
        preview={{ ...preview, can_import: false, message: "章节：文本不能为空。没有写入任何数据。" }}
        previewError="不支持的作品包格式版本：2。当前只接受版本 1。没有写入任何数据。"
        importPending={false}
        onChooseFile={vi.fn()}
        onConfirmImport={vi.fn()}
        onCancelPreview={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert").textContent).toContain("不支持的作品包格式版本：2");
    expect(screen.getByRole("button", { name: "导入为新作品" })).toHaveProperty("disabled", true);
  });
});

function emptyCounts(overrides: Partial<PortablePreview["created"]> = {}): PortablePreview["created"] {
  return {
    novels: 0,
    volumes: 0,
    chapters: 0,
    chapter_versions: 0,
    story_plans: 0,
    chapter_outlines: 0,
    scene_cards: 0,
    entities: 0,
    entity_states: 0,
    relations: 0,
    events: 0,
    summaries: 0,
    proposals: 0,
    foreshadowing: 0,
    writing_goals: 0,
    quality_issues: 0,
    repair_candidates: 0,
    ai_tasks: 0,
    model_configs: 0,
    ...overrides,
  };
}
