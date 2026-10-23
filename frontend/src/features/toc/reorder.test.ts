import { describe, expect, it } from "vitest";
import { moveVolumeToStart, planChapterMove, planVolumeMove } from "./reorder.ts";

describe("toc reorder", () => {
  it("moves a chapter down inside the same volume", () => {
    expect(planChapterMove(["a", "b", "c"], "a", ["a", "b", "c"], "c", "after")).toBe(2);
  });

  it("moves a chapter into another volume ahead of the target", () => {
    expect(planChapterMove(["a", "b"], "a", ["c"], "c", "before")).toBe(0);
  });

  it("appends a chapter when it is dropped on a volume", () => {
    expect(planChapterMove(["a"], "a", ["c", "d"], null, "end")).toBe(2);
  });

  it("skips a drop that would not change the order", () => {
    expect(planChapterMove(["a", "b"], "b", ["a", "b"], "b", "after")).toBeNull();
    expect(planChapterMove(["a", "b"], "a", ["a", "b"], "a", "before")).toBeNull();
  });

  it("reorders volumes and can move one to the front", () => {
    expect(planVolumeMove(["v1", "v2", "v3"], "v3", "v1", "before")).toEqual(["v3", "v1", "v2"]);
    expect(planVolumeMove(["v1", "v2"], "v1", "v1", "after")).toBeNull();
    expect(moveVolumeToStart(["v1", "v2"], "v2")).toEqual(["v2", "v1"]);
    expect(moveVolumeToStart(["v1", "v2"], "v1")).toBeNull();
  });
});
