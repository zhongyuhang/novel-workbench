export type StreamEventName =
  | "task.started"
  | "token"
  | "task.completed"
  | "task.failed"
  | "task.cancelled"
  | "heartbeat";

export type StreamEvent = {
  event: StreamEventName;
  data: {
    text?: string;
    output_text?: string;
    error_message?: string;
    error_code?: string;
    partial?: boolean;
    provider_mode?: "mock" | "openai_compatible";
    status?: string;
  };
};

export type CandidateState = {
  text: string;
  status: "idle" | "running" | "completed" | "failed" | "cancelled";
  ignoreTokens: boolean;
  completedCount: number;
  errorMessage: string;
  providerMode: "mock" | "openai_compatible" | null;
  disconnected: boolean;
  partial: boolean;
};

export const idleCandidate: CandidateState = {
  text: "",
  status: "idle",
  ignoreTokens: false,
  completedCount: 0,
  errorMessage: "",
  providerMode: null,
  disconnected: false,
  partial: false,
};

export function reduceCandidate(state: CandidateState, event: StreamEvent): CandidateState {
  if (event.event === "heartbeat") {
    return state;
  }
  const providerMode = event.data.provider_mode ?? state.providerMode;
  if (event.event === "task.started") {
    if (isTerminal(state.status)) {
      return state;
    }
    return { ...state, status: "running", providerMode, disconnected: false };
  }
  if (event.event === "token") {
    if (state.ignoreTokens || isTerminal(state.status)) {
      return state;
    }
    return {
      ...state,
      status: "running",
      providerMode,
      text: state.text + (event.data.text ?? ""),
      disconnected: false,
    };
  }
  if (event.event === "task.completed") {
    if (state.completedCount > 0 || state.status === "cancelled" || state.status === "failed") {
      return state;
    }
    return {
      ...state,
      status: "completed",
      providerMode,
      text: event.data.output_text ?? state.text,
      completedCount: state.completedCount + 1,
      disconnected: false,
      partial: event.data.partial === true,
      errorMessage:
        event.data.partial === true
          ? (event.data.error_message ?? "模型中断前已经写出一段正文，可以采纳这段片段。")
          : "",
    };
  }
  if (event.event === "task.failed") {
    if (state.status === "cancelled" || state.status === "completed") {
      return state;
    }
    return {
      ...state,
      status: "failed",
      ignoreTokens: true,
      providerMode,
      partial: false,
      errorMessage: event.data.error_message ?? "生成没有完成。正文没有被修改。",
      disconnected: false,
    };
  }
  return {
    ...state,
    status: "cancelled",
    ignoreTokens: true,
    providerMode,
    partial: false,
    disconnected: false,
  };
}

function isTerminal(status: CandidateState["status"]): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}
