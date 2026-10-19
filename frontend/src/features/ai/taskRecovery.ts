import {
  reduceCandidate,
  type CandidateState,
} from "./candidateStream.ts";

export type TaskSnapshot = {
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  output_text: string | null;
  error_message_safe: string | null;
  provider_mode: "mock" | "openai_compatible";
};

export function stateFromTask(previous: CandidateState, task: TaskSnapshot): CandidateState {
  const providerMode = task.provider_mode;
  if (task.status === "completed") {
    return {
      ...reduceCandidate(previous, {
        event: "task.completed",
        data: {
          output_text: task.output_text ?? "",
          provider_mode: providerMode,
          status: task.status,
        },
      }),
      disconnected: false,
    };
  }
  if (task.status === "failed") {
    return {
      ...reduceCandidate(previous, {
        event: "task.failed",
        data: {
          error_message: task.error_message_safe ?? "生成没有完成。正文没有被修改。",
          provider_mode: providerMode,
          status: task.status,
        },
      }),
      disconnected: false,
    };
  }
  if (task.status === "cancelled") {
    const cancelled = reduceCandidate(previous, {
      event: "task.cancelled",
      data: { provider_mode: providerMode, status: task.status },
    });
    return {
      ...cancelled,
      text: task.output_text ?? previous.text,
      disconnected: false,
    };
  }
  return {
    ...previous,
    status: "running",
    providerMode,
    text: previous.text || task.output_text || "",
    disconnected: true,
    errorMessage: "",
  };
}
