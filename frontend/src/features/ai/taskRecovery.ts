import {
  reduceCandidate,
  type CandidateState,
} from "./candidateStream.ts";
import { failurePresentation } from "./taskWatch.ts";

export type TaskSnapshot = {
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  output_text: string | null;
  error_message_safe: string | null;
  provider_mode: "mock" | "openai_compatible";
  partial?: boolean;
  error_code?: string | null;
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
          partial: task.partial === true,
          error_message: task.partial === true ? (task.error_message_safe ?? undefined) : undefined,
        },
      }),
      disconnected: false,
    };
  }
  if (task.status === "failed") {
    const failure = failurePresentation(task.error_code, task.error_message_safe);
    return {
      ...reduceCandidate(previous, {
        event: "task.failed",
        data: {
          error_message: failure.message,
          error_code: task.error_code ?? undefined,
          provider_mode: providerMode,
          status: task.status,
        },
      }),
      canRetry: failure.canRetry,
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
