import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary.tsx";

function Boom(): never {
  throw new Error("面板崩了");
}

let crashPanel = true;

function Flaky() {
  if (crashPanel) {
    throw new Error("面板还在崩");
  }
  return <p>设定恢复了</p>;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    crashPanel = true;
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("shows the failed panel and leaves the rest of the page up", () => {
    render(
      <div>
        <p>目录还在</p>
        <ErrorBoundary title="设定">
          <Boom />
        </ErrorBoundary>
      </div>,
    );

    expect(screen.getByText("目录还在")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("设定暂时打不开");
    expect(screen.getByRole("alert").textContent).toContain("其他部分还可以继续用");
  });

  it("retries the panel without remounting the page", async () => {
    const user = userEvent.setup();
    render(
      <ErrorBoundary title="设定">
        <Flaky />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toBeTruthy();
    crashPanel = false;
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("设定恢复了")).toBeTruthy();
  });
});
