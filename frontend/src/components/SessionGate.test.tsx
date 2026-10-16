import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { openSession, readToken } from "../api/client.ts";
import { ApiError } from "../api/types.ts";
import { SessionGate } from "./SessionGate.tsx";

vi.mock("../api/client.ts", () => ({
  openSession: vi.fn(),
  readToken: vi.fn(() => null),
  SESSION_REQUIRED_EVENT: "ai-novel-writer:session-required",
}));

describe("SessionGate", () => {
  beforeEach(() => {
    vi.mocked(readToken).mockReturnValue(null);
    vi.mocked(openSession).mockReset();
  });

  it("asks for a password when the server requires one", async () => {
    vi.mocked(openSession).mockRejectedValue(
      new ApiError(401, "PASSWORD_REQUIRED", "需要访问口令。", "req-1"),
    );

    render(
      <SessionGate>
        <p>作品库</p>
      </SessionGate>,
    );

    expect(await screen.findByRole("heading", { name: "访问口令" })).toBeTruthy();
    expect(screen.queryByText("作品库")).toBeNull();
  });

  it("enters the library after a successful login", async () => {
    vi.mocked(openSession)
      .mockRejectedValueOnce(new ApiError(401, "PASSWORD_REQUIRED", "需要访问口令。", "req-1"))
      .mockResolvedValueOnce(undefined);
    const user = userEvent.setup();

    render(
      <SessionGate>
        <p>作品库</p>
      </SessionGate>,
    );

    await screen.findByRole("heading", { name: "访问口令" });
    await user.type(screen.getByLabelText("口令"), "correct-horse");
    await user.click(screen.getByRole("button", { name: "进入作品库" }));

    expect(await screen.findByText("作品库")).toBeTruthy();
    expect(openSession).toHaveBeenLastCalledWith("correct-horse");
  });
});
