import { afterEach, describe, expect, it, vi } from "vitest";
import {
  apiRequest,
  DEFAULT_REQUEST_TIMEOUT_MS,
  GENERATE_REQUEST_TIMEOUT_MS,
  isLongRunningRequest,
} from "./client.ts";
import { ApiError } from "./types.ts";

function hang(init: RequestInit | undefined): Promise<Response> {
  return new Promise((_resolve, reject) => {
    const signal = init?.signal;
    if (!signal) {
      return;
    }
    const fail = () => {
      reject(new DOMException("aborted", "AbortError"));
    };
    if (signal.aborted) {
      fail();
      return;
    }
    signal.addEventListener("abort", fail, { once: true });
  });
}

describe("request timeouts", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("treats generation streams as longer than the default timeout", () => {
    expect(isLongRunningRequest("/api/v1/novels")).toBe(false);
    expect(isLongRunningRequest("/api/v1/ai/tasks/abc/events")).toBe(true);
    expect(isLongRunningRequest("/api/v1/chapters/abc/analyze")).toBe(true);
    expect(isLongRunningRequest("/api/v1/ai/tasks?chapter_id=abc")).toBe(false);
    expect(GENERATE_REQUEST_TIMEOUT_MS).toBeGreaterThan(DEFAULT_REQUEST_TIMEOUT_MS);
    expect(GENERATE_REQUEST_TIMEOUT_MS).toBeGreaterThanOrEqual(300_000);
  });

  it("turns a hung read into a timeout error", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => hang(init)));
    let result: unknown = "pending";
    const pending = apiRequest("/api/v1/novels").then(
      () => {
        result = "ok";
      },
      (error: unknown) => {
        result = error;
      },
    );

    await vi.advanceTimersByTimeAsync(DEFAULT_REQUEST_TIMEOUT_MS);
    await pending;

    expect(result).toBeInstanceOf(ApiError);
    expect(result).toMatchObject({ code: "TIMEOUT" });
    expect((result as ApiError).message).toContain("超时");
  });

  it("does not time out a generation stream at the default limit", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => hang(init)));
    let result: unknown = "pending";
    const pending = apiRequest("/api/v1/ai/tasks/task-1/events").then(
      () => {
        result = "ok";
      },
      (error: unknown) => {
        result = error;
      },
    );

    await vi.advanceTimersByTimeAsync(DEFAULT_REQUEST_TIMEOUT_MS);
    expect(result).toBe("pending");

    await vi.advanceTimersByTimeAsync(GENERATE_REQUEST_TIMEOUT_MS - DEFAULT_REQUEST_TIMEOUT_MS);
    await pending;
    expect(result).toBeInstanceOf(ApiError);
    expect(result).toMatchObject({ code: "TIMEOUT" });
  });

  it("lets the caller abort without calling it a timeout", async () => {
    vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) => hang(init)));
    const controller = new AbortController();
    const pending = apiRequest("/api/v1/novels", { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
