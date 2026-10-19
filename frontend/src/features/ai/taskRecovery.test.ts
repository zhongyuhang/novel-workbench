import { describe, expect, it } from "vitest";
import { idleCandidate, reduceCandidate } from "./candidateStream.ts";
import { stateFromTask } from "./taskRecovery.ts";

describe("task recovery", () => {
  it("uses the stored candidate when the stream never finished", () => {
    const running = reduceCandidate(idleCandidate, {
      event: "task.started",
      data: { provider_mode: "mock" },
    });
    const recovered = stateFromTask(running, {
      status: "completed",
      output_text: "服务器上的候选",
      error_message_safe: null,
      provider_mode: "mock",
    });

    expect(recovered.status).toBe("completed");
    expect(recovered.text).toBe("服务器上的候选");
    expect(recovered.disconnected).toBe(false);
  });

  it("keeps a cancelled task from being completed by a late result", () => {
    const cancelled = reduceCandidate(
      reduceCandidate(idleCandidate, { event: "token", data: { text: "甲" } }),
      { event: "task.cancelled", data: {} },
    );
    const recovered = stateFromTask(cancelled, {
      status: "cancelled",
      output_text: "甲",
      error_message_safe: null,
      provider_mode: "mock",
    });
    const late = stateFromTask(recovered, {
      status: "completed",
      output_text: "甲乙",
      error_message_safe: null,
      provider_mode: "mock",
    });

    expect(late.status).toBe("cancelled");
    expect(late.text).toBe("甲");
  });

  it("keeps an unfinished task visible after the connection drops", () => {
    const recovered = stateFromTask(idleCandidate, {
      status: "running",
      output_text: "已写到的片段",
      error_message_safe: null,
      provider_mode: "openai_compatible",
    });

    expect(recovered.status).toBe("running");
    expect(recovered.disconnected).toBe(true);
    expect(recovered.text).toBe("已写到的片段");
  });

  it("shows a safe failure from the task row", () => {
    const recovered = stateFromTask(idleCandidate, {
      status: "failed",
      output_text: null,
      error_message_safe: "模型服务限流了。请稍后再试。",
      provider_mode: "openai_compatible",
    });

    expect(recovered.status).toBe("failed");
    expect(recovered.text).toBe("");
    expect(recovered.errorMessage).toContain("限流");
  });
});
