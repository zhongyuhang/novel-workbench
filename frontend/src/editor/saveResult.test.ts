import { describe, expect, it } from "vitest";
import { interpretSaveConflict, interpretSaveSuccess } from "./saveResult.ts";

const same = {
  sentCanonical: "a",
  currentCanonical: "a",
  sentTitle: "标题",
  currentTitle: "标题",
  sentStatus: "draft",
  currentStatus: "draft",
};

describe("save result interpretation", () => {
  it("ignores an older response after a newer save has started", () => {
    expect(
      interpretSaveSuccess({
        requestGeneration: 1,
        latestGeneration: 2,
        savedRevision: 3,
        currentRevision: 2,
        ...same,
      }),
    ).toEqual({ applyRevision: false, markBaseline: false });
    expect(interpretSaveConflict({ requestGeneration: 1, latestGeneration: 2 })).toBe("ignore");
  });

  it("does not move the revision backward", () => {
    expect(
      interpretSaveSuccess({
        requestGeneration: 2,
        latestGeneration: 2,
        savedRevision: 2,
        currentRevision: 4,
        ...same,
        currentCanonical: "newer",
      }),
    ).toEqual({ applyRevision: false, markBaseline: false });
  });

  it("keeps a newer local draft dirty after an older payload is stored", () => {
    expect(
      interpretSaveSuccess({
        requestGeneration: 1,
        latestGeneration: 1,
        savedRevision: 2,
        currentRevision: 1,
        ...same,
        currentCanonical: "newer",
        currentTitle: "新标题",
      }),
    ).toEqual({ applyRevision: true, markBaseline: false });
  });

  it("marks a conflict only for the latest request", () => {
    expect(interpretSaveConflict({ requestGeneration: 4, latestGeneration: 4 })).toBe("conflict");
  });
});
