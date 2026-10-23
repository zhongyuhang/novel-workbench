import type { AiTask, AiTaskStatus } from "../../api/types.ts";
import type { CandidateState } from "./candidateStream.ts";

export const BACKGROUND_POLL_MS = 3000;

export const BACKGROUND_MESSAGE =
  "仍在后台生成。可以稍后查看这一章。这次等待不会取消任务，正文也不会被自动改写。";

export const READY_MESSAGE = "候选已经写好，可以采纳或放弃。正文还没改。";

export const CANCELLED_WITH_TEXT_MESSAGE =
  "生成停了，但已经有一段正文。可以采纳这段片段，也可以放弃。正文还没被改写。";

export type GenerationPhase = "background" | "ready" | "failed" | "cancelled";

export type GenerationActivity = {
  phase: GenerationPhase;
  message: string;
};

export type WatchTask = {
  status: AiTaskStatus;
  output_text: string | null;
  error_code?: string | null;
  error_message_safe?: string | null;
  partial?: boolean;
  resolution?: "accepted" | "rejected" | null;
  created_at?: string;
  provider_mode?: "mock" | "openai_compatible";
};

/** Stopping a poll is not a cancel. The server task keeps running. */
export function abandonWatch(): { cancelTask: false; message: string } {
  return { cancelTask: false, message: BACKGROUND_MESSAGE };
}

export function failurePresentation(
  code: string | null | undefined,
  serverMessage: string | null | undefined,
): { message: string; canRetry: boolean } {
  if (code === "EMPTY_OUTPUT") {
    const message =
      serverMessage?.trim() || "模型这次没有写出可用正文。正文没有改动，可以再试一次。";
    return { message, canRetry: !message.includes("内容过滤") };
  }
  if (code === "MODEL_TIMEOUT") {
    return {
      message: "模型超时，没有留下可采纳的正文。可以再试一次。",
      canRetry: true,
    };
  }
  if (code === "POLL_TIMEOUT") {
    return { message: BACKGROUND_MESSAGE, canRetry: false };
  }
  if (
    code === "MODEL_NOT_CONFIGURED" ||
    code === "MODEL_CONFIG_INVALID" ||
    code === "SECRET_STORAGE_UNAVAILABLE"
  ) {
    return {
      message: serverMessage?.trim() || "模型配置还不能用。请先到模型设置检查。",
      canRetry: false,
    };
  }
  if (serverMessage?.trim()) {
    return { message: serverMessage.trim(), canRetry: true };
  }
  return { message: "生成没有完成。正文没有被修改。可以再试一次。", canRetry: true };
}

export function canAdoptCandidate(candidate: Pick<CandidateState, "status" | "text">): boolean {
  return (
    candidate.text.trim() !== "" &&
    (candidate.status === "completed" || candidate.status === "cancelled")
  );
}

export function pickOpenTask<T extends WatchTask>(tasks: T[]): T | null {
  const open = tasks.filter((task) => task.resolution == null);
  const live = open.find((task) => task.status === "running" || task.status === "queued");
  if (live) {
    return live;
  }
  return (
    open.find(
      (task) =>
        (task.status === "completed" || task.status === "cancelled") &&
        (task.output_text ?? "").trim() !== "",
    ) ?? null
  );
}

export function noticeForTask(task: WatchTask): string {
  if (task.status === "queued" || task.status === "running") {
    return BACKGROUND_MESSAGE;
  }
  if (task.status === "failed") {
    return failurePresentation(task.error_code, task.error_message_safe).message;
  }
  if (task.status === "cancelled") {
    return (task.output_text ?? "").trim()
      ? CANCELLED_WITH_TEXT_MESSAGE
      : "已取消。正文没有被改写。";
  }
  if (task.partial) {
    return task.error_message_safe?.trim() || "模型中断了，下面是已生成的片段，可以采纳。";
  }
  if ((task.output_text ?? "").trim()) {
    return READY_MESSAGE;
  }
  return "";
}

export function activityFromCandidate(
  candidate: Pick<CandidateState, "status" | "text" | "errorMessage" | "partial">,
): GenerationActivity | null {
  if (candidate.status === "idle") {
    return null;
  }
  if (candidate.status === "running") {
    return { phase: "background", message: BACKGROUND_MESSAGE };
  }
  if (candidate.status === "completed") {
    return {
      phase: "ready",
      message: candidate.partial
        ? candidate.errorMessage || "模型中断了，下面是已生成的片段，可以采纳。"
        : READY_MESSAGE,
    };
  }
  if (candidate.status === "failed") {
    return {
      phase: "failed",
      message: candidate.errorMessage || "生成没有完成。正文没有被修改。",
    };
  }
  return {
    phase: "cancelled",
    message: candidate.text.trim() ? CANCELLED_WITH_TEXT_MESSAGE : "已取消。正文没有被改写。",
  };
}

export async function followOpenTask(
  read: () => Promise<WatchTask>,
  hooks: {
    signal: AbortSignal;
    wait: (ms: number, signal: AbortSignal) => Promise<void>;
    onTask: (task: WatchTask) => void;
    intervalMs?: number;
  },
): Promise<void> {
  const intervalMs = hooks.intervalMs ?? BACKGROUND_POLL_MS;
  try {
    while (!hooks.signal.aborted) {
      const task = await read();
      if (hooks.signal.aborted) {
        return;
      }
      hooks.onTask(task);
      if (task.status !== "queued" && task.status !== "running") {
        return;
      }
      await hooks.wait(intervalMs, hooks.signal);
    }
  } catch (error: unknown) {
    if (isAbort(error)) {
      return;
    }
    throw error;
  }
}

export function waitWithSignal(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError());
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export function taskWatchSnapshot(task: AiTask): WatchTask {
  return {
    status: task.status,
    output_text: task.output_text,
    error_code: task.error_code,
    error_message_safe: task.error_message_safe,
    partial: task.partial,
    resolution: task.resolution,
    created_at: task.created_at,
    provider_mode: task.provider_mode,
  };
}

function abortError(): DOMException {
  return new DOMException("aborted", "AbortError");
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
