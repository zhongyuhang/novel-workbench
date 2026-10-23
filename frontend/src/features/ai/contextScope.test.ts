import { describe, expect, it } from "vitest";
import { excludeIdsForScope, localPromptPreview, scopeLabel } from "./contextScope.ts";

const items = [
  { id: "chapter", kind: "chapter", content: "正文" },
  { id: "hard-rule", kind: "hard_rule", content: "短句" },
  { id: "outline:1", kind: "chapter_outline", content: "大纲" },
  { id: "entity:1", kind: "entity", content: "已确认设定：人物「林晚」" },
  { id: "entity:2", kind: "entity", content: "已确认设定：地点「城门」" },
  { id: "prev:1", kind: "previous_chapter", content: "上一章" },
];

describe("context scope", () => {
  it("keeps only the chapter and hard rules until outline or characters are added", () => {
    expect(excludeIdsForScope(items, { outline: false, characters: false }, [])).toEqual([
      "outline:1",
      "entity:1",
      "entity:2",
      "prev:1",
    ]);
    expect(excludeIdsForScope(items, { outline: true, characters: false }, [])).toEqual([
      "entity:1",
      "entity:2",
      "prev:1",
    ]);
    expect(excludeIdsForScope(items, { outline: true, characters: true }, [])).toEqual([
      "entity:2",
      "prev:1",
    ]);
  });

  it("does not exclude a material the author pinned", () => {
    expect(excludeIdsForScope(items, { outline: false, characters: false }, ["outline:1"])).toEqual([
      "entity:1",
      "entity:2",
      "prev:1",
    ]);
  });

  it("describes the scope inside the prompt preview", () => {
    expect(scopeLabel({ outline: false, characters: false })).toBe("仅本章");
    expect(scopeLabel({ outline: true, characters: true })).toBe("本章 + 大纲 + 角色设定");
    expect(
      localPromptPreview({
        taskLabel: "续写",
        instruction: "雨声",
        selection: "",
        maxWords: "200",
        mustInclude: "",
        mustAvoid: "解释",
        scopeLabel: "仅本章",
      }),
    ).toBe("动作：续写\n上下文：仅本章\n指令：雨声\n最多字数：200\n不要出现：解释");
  });
});
