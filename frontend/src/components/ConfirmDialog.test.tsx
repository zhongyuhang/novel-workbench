import { describe, expect, it, vi } from "vitest";
import { confirmDialog } from "./ConfirmDialog.tsx";

describe("confirmDialog", () => {
  it("uses the native confirm when the dialog host is not mounted", async () => {
    const spy = vi.spyOn(window, "confirm").mockReturnValue(false);
    await expect(confirmDialog("离开？")).resolves.toBe(false);
    expect(spy).toHaveBeenCalledWith("离开？");
    spy.mockRestore();
  });
});
