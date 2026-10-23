import type { CompiledContext, ContextItem } from "../../api/types.ts";

export type ContextScope = {
  outline: boolean;
  characters: boolean;
};

const KEPT_KINDS = new Set(["system", "instruction", "constraints", "hard_rule", "chapter"]);

const OUTLINE_KINDS = new Set([
  "story_plan",
  "story_arc",
  "volume_outline",
  "chapter_outline",
  "scene_card",
]);

export function isCharacterMaterial(item: Pick<ContextItem, "kind" | "content">): boolean {
  if (item.kind === "entity_relation") {
    return true;
  }
  return item.kind === "entity" && item.content.includes("：人物「");
}

/**
 * Material ids to pass as pinned_exclude for this scope.
 * Explicit pins stay included. System rules and the current chapter always stay.
 */
export function excludeIdsForScope(
  items: Array<Pick<ContextItem, "id" | "kind" | "content">>,
  scope: ContextScope,
  pinnedInclude: string[],
): string[] {
  const pinned = new Set(pinnedInclude);
  const ids: string[] = [];
  for (const item of items) {
    if (KEPT_KINDS.has(item.kind) || pinned.has(item.id)) {
      continue;
    }
    if (OUTLINE_KINDS.has(item.kind)) {
      if (!scope.outline) {
        ids.push(item.id);
      }
      continue;
    }
    if (isCharacterMaterial(item)) {
      if (!scope.characters) {
        ids.push(item.id);
      }
      continue;
    }
    ids.push(item.id);
  }
  return ids;
}

export function scopeLabel(scope: ContextScope): string {
  if (!scope.outline && !scope.characters) {
    return "仅本章";
  }
  const parts = ["本章"];
  if (scope.outline) {
    parts.push("大纲");
  }
  if (scope.characters) {
    parts.push("角色设定");
  }
  return parts.join(" + ");
}

export function localPromptPreview(input: {
  taskLabel: string;
  instruction: string;
  selection: string;
  maxWords: string;
  mustInclude: string;
  mustAvoid: string;
  scopeLabel: string;
}): string {
  const lines = [`动作：${input.taskLabel}`, `上下文：${input.scopeLabel}`];
  if (input.selection.trim()) {
    lines.push(`选区：${input.selection.trim()}`);
  }
  lines.push(`指令：${input.instruction.trim() || "（没有额外指令）"}`);
  if (input.maxWords.trim()) {
    lines.push(`最多字数：${input.maxWords.trim()}`);
  }
  if (input.mustInclude.trim()) {
    lines.push(`必须包含：${input.mustInclude.trim()}`);
  }
  if (input.mustAvoid.trim()) {
    lines.push(`不要出现：${input.mustAvoid.trim()}`);
  }
  return lines.join("\n");
}

export function compiledPromptText(context: CompiledContext): string {
  const included = context.items.filter((item) => item.included && item.content.trim());
  if (included.length === 0) {
    return "（这次编译没有纳入材料）";
  }
  return included.map((item) => item.content.trim()).join("\n\n");
}
