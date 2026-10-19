import { describe, expect, it } from "vitest";
import { diffLines } from "./textDiff.ts";

describe("diffLines", () => {
  it("shows inserted and deleted lines", () => {
    expect(diffLines("第一段\n旧句子", "第一段\n新句子")).toEqual([
      { op: "equal", text: "第一段" },
      { op: "delete", text: "旧句子" },
      { op: "insert", text: "新句子" },
    ]);
  });

  it("returns nothing when both sides are empty", () => {
    expect(diffLines("", "")).toEqual([]);
  });
});
