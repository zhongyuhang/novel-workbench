import { describe, expect, it, vi } from "vitest";
import { idleCandidate } from "./candidateStream.ts";
import {
  abandonWatch,
  activityFromCandidate,
  BACKGROUND_MESSAGE,
  canAdoptCandidate,
  failurePresentation,
  followOpenTask,
  pickOpenTask,
  type WatchTask,
} from "./taskWatch.ts";

describe("task watch", () => {
  it("does not cancel when a poll is abandoned", () => {
    const decision = abandonWatch();
    expect(decision.cancelTask).toBe(false);
    expect(decision.message).toContain("不会取消");
    expect(decision.message).toContain("后台");
  });

  it("follows a running task until it can be adopted, without a cancel step", async () => {
    const seen: WatchTask["status"][] = [];
    const tasks: WatchTask[] = [
      { status: "running", output_text: "已写到", error_code: null, error_message_safe: null },
      { status: "completed", output_text: "已写到的全文", error_code: null, error_message_safe: null },
    ];
    const cancel = vi.fn();
    await followOpenTask(
      async () => {
        const next = tasks.shift();
        if (!next) {
          throw new Error("no task");
        }
        return next;
      },
      {
        signal: new AbortController().signal,
        wait: async () => {},
        onTask: (task) => {
          seen.push(task.status);
        },
      },
    );

    expect(cancel).not.toHaveBeenCalled();
    expect(seen).toEqual(["running", "completed"]);
  });

  it("stops following when the watch is aborted and does not cancel", async () => {
    const controller = new AbortController();
    const cancel = vi.fn();
    let reads = 0;
    const done = followOpenTask(
      async () => {
        reads += 1;
        return { status: "running", output_text: "还在写", error_code: null, error_message_safe: null };
      },
      {
        signal: controller.signal,
        wait: async (_ms, signal) => {
          controller.abort();
          if (signal.aborted) {
            throw new DOMException("aborted", "AbortError");
          }
        },
        onTask: () => {},
      },
    );

    await done;
    expect(cancel).not.toHaveBeenCalled();
    expect(reads).toBe(1);
  });

  it("prefers an in-flight task, then an unused candidate", () => {
    const running: WatchTask = { status: "running", output_text: "", error_code: null, error_message_safe: null };
    const ready: WatchTask = {
      status: "completed",
      output_text: "可采纳",
      error_code: null,
      error_message_safe: null,
      resolution: null,
    };
    expect(pickOpenTask([ready, running])?.status).toBe("running");
    expect(pickOpenTask([ready])?.output_text).toBe("可采纳");
    const stranded: WatchTask = {
      status: "cancelled",
      output_text: "停下来的正文",
      error_code: null,
      error_message_safe: null,
    };
    expect(pickOpenTask([stranded])?.status).toBe("cancelled");
    expect(pickOpenTask([{ ...ready, resolution: "accepted" }])).toBeNull();
  });

  it("explains empty output, timeout, and poll give-up in plain language", () => {
    const empty = failurePresentation("EMPTY_OUTPUT", "模型这次没有写出可用正文。正文没有改动，可以再试一次。");
    expect(empty.message).toContain("没有写出");
    expect(empty.canRetry).toBe(true);

    const filtered = failurePresentation("EMPTY_OUTPUT", "模型因为内容过滤停了，没有写出可用正文。正文没有改动。");
    expect(filtered.canRetry).toBe(false);

    const timeout = failurePresentation("MODEL_TIMEOUT", "模型请求超时。");
    expect(timeout.message).toContain("再试一次");
    expect(timeout.canRetry).toBe(true);

    const poll = failurePresentation("POLL_TIMEOUT", "POLL_TIMEOUT");
    expect(poll.message).toBe(BACKGROUND_MESSAGE);
    expect(poll.canRetry).toBe(false);
  });

  it("marks a cancelled fragment as adoptable and a failure as visible in focus", () => {
    expect(canAdoptCandidate({ status: "cancelled", text: "片段" })).toBe(true);
    expect(canAdoptCandidate({ status: "cancelled", text: "  " })).toBe(false);
    expect(canAdoptCandidate({ status: "completed", text: "全文" })).toBe(true);
    expect(canAdoptCandidate({ status: "failed", text: "" })).toBe(false);

    const running = activityFromCandidate({ ...idleCandidate, status: "running" });
    expect(running?.phase).toBe("background");
    expect(running?.message).toContain("后台");

    const failed = activityFromCandidate({
      ...idleCandidate,
      status: "failed",
      errorMessage: "模型这次没有写出可用正文。",
    });
    expect(failed?.phase).toBe("failed");
    expect(failed?.message).toContain("没有写出");
  });
});
