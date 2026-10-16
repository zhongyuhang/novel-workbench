import { describe, expect, it, vi } from "vitest";
import { UNSAVED_LEAVE_MESSAGE, allowChapterLeave } from "./leaveGuard.ts";

describe("allowChapterLeave", () => {
  it("allows a clean chapter without asking", () => {
    const ask = vi.fn(() => false);
    expect(allowChapterLeave(false, ask)).toBe(true);
    expect(ask).not.toHaveBeenCalled();
  });

  it("asks before leaving unsaved work", () => {
    const ask = vi.fn(() => false);
    expect(allowChapterLeave(true, ask)).toBe(false);
    expect(ask).toHaveBeenCalledWith(UNSAVED_LEAVE_MESSAGE);
    ask.mockReturnValue(true);
    expect(allowChapterLeave(true, ask)).toBe(true);
  });
});
