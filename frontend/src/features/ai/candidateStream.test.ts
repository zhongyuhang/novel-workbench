import { describe, expect, it } from "vitest";
import { idleCandidate, reduceCandidate } from "./candidateStream.ts";

describe("candidate stream", () => {
  it("appends tokens in order and records completed once", () => {
    let state = reduceCandidate(idleCandidate, { event: "task.started", data: { provider_mode: "mock" } });
    state = reduceCandidate(state, { event: "token", data: { text: "甲" } });
    state = reduceCandidate(state, { event: "token", data: { text: "乙" } });
    state = reduceCandidate(state, { event: "heartbeat", data: {} });
    state = reduceCandidate(state, {
      event: "task.completed",
      data: { output_text: "甲乙", provider_mode: "mock" },
    });
    state = reduceCandidate(state, { event: "task.completed", data: { output_text: "忽略" } });

    expect(state.text).toBe("甲乙");
    expect(state.status).toBe("completed");
    expect(state.completedCount).toBe(1);
    expect(state.providerMode).toBe("mock");
  });

  it("ignores tokens that arrive after cancel", () => {
    let state = reduceCandidate(idleCandidate, { event: "token", data: { text: "甲" } });
    state = reduceCandidate(state, { event: "task.cancelled", data: {} });
    state = reduceCandidate(state, { event: "token", data: { text: "乙" } });
    state = reduceCandidate(state, { event: "task.completed", data: { output_text: "甲乙" } });

    expect(state.status).toBe("cancelled");
    expect(state.text).toBe("甲");
    expect(state.completedCount).toBe(0);
  });

  it("does not turn a failure into a completed candidate", () => {
    const state = reduceCandidate(idleCandidate, {
      event: "task.failed",
      data: { error_message: "模型请求超时。正文没有被修改。" },
    });
    const late = reduceCandidate(state, { event: "task.completed", data: { output_text: "不该成功" } });

    expect(late.status).toBe("failed");
    expect(late.text).toBe("");
    expect(late.errorMessage).toContain("超时");
  });

  it("keeps a timed-out fragment as a candidate that can be accepted", () => {
    let state = reduceCandidate(idleCandidate, { event: "token", data: { text: "已写" } });
    state = reduceCandidate(state, { event: "token", data: { text: "出一段" } });
    state = reduceCandidate(state, {
      event: "task.completed",
      data: {
        output_text: "已写出一段",
        partial: true,
        error_code: "MODEL_TIMEOUT",
        error_message: "模型超时，已保留已生成的片段。正文还没改，可以采纳这段候选。",
      },
    });

    expect(state.status).toBe("completed");
    expect(state.partial).toBe(true);
    expect(state.text).toBe("已写出一段");
    expect(state.errorMessage).toContain("可以采纳");
  });
});
