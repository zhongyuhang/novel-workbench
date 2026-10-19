import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type Chapter } from "../api/types.ts";
import {
  acceptRepair,
  generateRepairs,
  listQualityIssues,
  runQualityCheck,
  updateQualityIssue,
  type QualityIssue,
} from "../api/quality.ts";
import { QualityIssuesSection } from "./QualityIssuesSection.tsx";

vi.mock("../api/quality.ts", () => ({
  listQualityIssues: vi.fn(),
  runQualityCheck: vi.fn(),
  updateQualityIssue: vi.fn(),
  generateRepairs: vi.fn(),
  acceptRepair: vi.fn(),
  rejectRepair: vi.fn(),
}));

const issue: QualityIssue = {
  id: "issue-1",
  novel_id: "novel-1",
  chapter_id: "chapter-1",
  chapter_title: "后文",
  issue_type: "fact_continuity",
  severity: "medium",
  confidence: 0.74,
  status: "pending",
  manuscript_snippet: "阿宁是右撇子。",
  target_revision: 2,
  location_note: null,
  evidence_status: "sufficient",
  evidence: [
    {
      kind: "manuscript",
      label: "当前正文片段",
      quote: "阿宁是右撇子。",
      source_chapter_id: "chapter-1",
      source_chapter_title: "后文",
      source_revision: 2,
      ref_id: null,
    },
    {
      kind: "story_event",
      label: "阿宁是左撇子",
      quote: "阿宁是左撇子",
      source_chapter_id: "chapter-0",
      source_chapter_title: "前文",
      source_revision: 1,
      ref_id: "event-1",
    },
  ],
  related_refs: [{ kind: "story_event", ref_id: "event-1", label: "阿宁是左撇子" }],
  rule_id: "fact.attribute_contradiction",
  rule_version: "quality_rules_v1",
  analysis_version: null,
  provider_mode: "rule",
  suggested_action: "请作者核对。这是疑似问题，不会自动修改正文或正式记忆。",
  fixed_revision: null,
  recheck_count: 0,
  candidates: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const savedChapter = {
  id: "chapter-1",
  novel_id: "novel-1",
  volume_id: null,
  title: "后文",
  sort_order: 1,
  word_count: 8,
  status: "draft",
  revision: 3,
  updated_at: "2026-01-02T00:00:00Z",
  content: { type: "doc" },
  content_format: "tiptap_json",
  content_format_version: 1,
  created_at: "2026-01-01T00:00:00Z",
} as Chapter;

describe("QualityIssuesSection", () => {
  beforeEach(() => {
    vi.mocked(listQualityIssues).mockReset();
    vi.mocked(runQualityCheck).mockReset();
    vi.mocked(updateQualityIssue).mockReset();
    vi.mocked(generateRepairs).mockReset();
    vi.mocked(acceptRepair).mockReset();
    vi.mocked(listQualityIssues).mockResolvedValue([issue]);
  });

  it("shows evidence and does not write while suggesting a diff", async () => {
    vi.mocked(runQualityCheck).mockResolvedValue({
      novel_id: "novel-1",
      chapter_id: null,
      provider_mode: "rule",
      rule_version: "quality_rules_v1",
      analysis_version: null,
      manuscript_changed: false,
      formal_memory_changed: false,
      issue_count: 1,
      expired_count: 0,
      reopened_count: 0,
      issues: [issue],
      message: "规则检查完成。模型检查未启用。正文和正式记忆都没有改动。",
    });
    vi.mocked(generateRepairs).mockResolvedValue({
      issue_id: issue.id,
      manuscript_changed: false,
      formal_memory_changed: false,
      provider_mode: "rule",
      message: "已根据规则生成修复建议。正文和正式记忆都没有改动。",
      candidates: [
        {
          id: "repair-1",
          issue_id: issue.id,
          novel_id: "novel-1",
          chapter_id: "chapter-1",
          target_revision: 2,
          apply_mode: "replace_selection",
          applicable: true,
          original_snippet: "阿宁是右撇子。",
          replacement_text: "阿宁是左撇子",
          rationale: "建议替换。这只是候选，不会自动修改正文或正式记忆。",
          diff_preview: "--- 当前正文\n+++ 建议正文\n-阿宁是右撇子。\n+阿宁是左撇子",
          provider_mode: "rule",
          prompt_version: "quality_repair_rules_v1",
          status: "proposed",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    });
    const user = userEvent.setup();
    render(<QualityIssuesSection novelId="novel-1" activeChapterId="chapter-1" />);

    expect(await screen.findByText("阿宁是右撇子。")).toBeTruthy();
    expect(screen.getByText("阿宁是左撇子")).toBeTruthy();
    expect(screen.getByText(/来源章节：前文/)).toBeTruthy();
    expect(screen.getByText(/不会自动修改正文或正式记忆/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /自动改正文|写入记忆/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: "运行规则检查" }));
    expect(runQualityCheck).toHaveBeenCalledWith("novel-1", {
      use_model: false,
      chapter_id: null,
    });

    await user.click(screen.getByRole("button", { name: "生成修复建议" }));
    expect(generateRepairs).toHaveBeenCalledWith(issue.id, false);
    expect(await screen.findByText(/--- 当前正文/)).toBeTruthy();
    expect(screen.getByText(/\+阿宁是左撇子/)).toBeTruthy();
    expect(acceptRepair).not.toHaveBeenCalled();
  });

  it("asks before accepting and reports a stale revision without hiding fixed issues", async () => {
    const onManuscriptUpdated = vi.fn();
    vi.mocked(listQualityIssues).mockImplementation(async (_novelId, options) =>
      options?.includeClosed ? [{ ...issue, status: "fixed" }] : [issue],
    );
    vi.mocked(acceptRepair).mockResolvedValue({
      manuscript_changed: true,
      formal_memory_changed: false,
      candidate: {
        id: "repair-1",
        issue_id: issue.id,
        novel_id: "novel-1",
        chapter_id: "chapter-1",
        target_revision: 2,
        apply_mode: "replace_selection",
        applicable: true,
        original_snippet: "阿宁是右撇子。",
        replacement_text: "阿宁是左撇子",
        rationale: "建议替换。",
        diff_preview: "--- 当前正文\n+++ 建议正文",
        provider_mode: "rule",
        prompt_version: "quality_repair_rules_v1",
        status: "accepted",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      issue: { ...issue, status: "fixed", candidates: [] },
      chapter: savedChapter,
      message: "已采纳这条建议，并留下新的正文版本。",
    });
    vi.mocked(generateRepairs).mockResolvedValue({
      issue_id: issue.id,
      manuscript_changed: false,
      formal_memory_changed: false,
      provider_mode: "rule",
      message: "已生成建议。",
      candidates: [
        {
          id: "repair-1",
          issue_id: issue.id,
          novel_id: "novel-1",
          chapter_id: "chapter-1",
          target_revision: 2,
          apply_mode: "replace_selection",
          applicable: true,
          original_snippet: "阿宁是右撇子。",
          replacement_text: "阿宁是左撇子",
          rationale: "建议替换。",
          diff_preview: "--- 当前正文\n+++ 建议正文",
          provider_mode: "rule",
          prompt_version: "quality_repair_rules_v1",
          status: "proposed",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(
      <QualityIssuesSection
        novelId="novel-1"
        activeChapterId="chapter-1"
        onManuscriptUpdated={onManuscriptUpdated}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "生成修复建议" }));
    await user.click(await screen.findByRole("button", { name: "采纳此建议" }));
    expect(confirm).toHaveBeenCalled();
    expect(acceptRepair).toHaveBeenCalledWith("repair-1", 2);
    expect(onManuscriptUpdated).toHaveBeenCalledWith(savedChapter);

    await user.click(screen.getByRole("checkbox", { name: "显示已修复、已忽略和已过期" }));
    expect(await screen.findByText(/已修复 · 中/)).toBeTruthy();
    confirm.mockRestore();
  });

  it("shows a conflict message and keeps the suggestion unapplied", async () => {
    vi.mocked(generateRepairs).mockResolvedValue({
      issue_id: issue.id,
      manuscript_changed: false,
      formal_memory_changed: false,
      provider_mode: "rule",
      message: "已生成建议。",
      candidates: [
        {
          id: "repair-1",
          issue_id: issue.id,
          novel_id: "novel-1",
          chapter_id: "chapter-1",
          target_revision: 2,
          apply_mode: "replace_selection",
          applicable: true,
          original_snippet: "阿宁是右撇子。",
          replacement_text: "阿宁是左撇子",
          rationale: "建议替换。",
          diff_preview: "--- 当前正文\n+++ 建议正文",
          provider_mode: "rule",
          prompt_version: "quality_repair_rules_v1",
          status: "proposed",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    });
    vi.mocked(acceptRepair).mockRejectedValue(
      new ApiError(409, "REVISION_CONFLICT", "目标修订已变化，没有覆盖新正文。请重新检查后再决定。", "req"),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<QualityIssuesSection novelId="novel-1" activeChapterId="chapter-1" />);

    await user.click(await screen.findByRole("button", { name: "生成修复建议" }));
    await user.click(await screen.findByRole("button", { name: "采纳此建议" }));
    expect((await screen.findByRole("alert")).textContent).toContain("没有覆盖新正文");
    expect(updateQualityIssue).not.toHaveBeenCalled();
  });
});
