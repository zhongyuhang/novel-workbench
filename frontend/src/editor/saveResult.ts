export type SaveSuccessDecision = {
  applyRevision: boolean;
  markBaseline: boolean;
};

export function interpretSaveSuccess(input: {
  requestGeneration: number;
  latestGeneration: number;
  savedRevision: number;
  currentRevision: number;
  sentCanonical: string;
  currentCanonical: string;
  sentTitle: string;
  currentTitle: string;
  sentStatus: string;
  currentStatus: string;
}): SaveSuccessDecision {
  if (input.requestGeneration < input.latestGeneration) {
    return { applyRevision: false, markBaseline: false };
  }
  const applyRevision = input.savedRevision >= input.currentRevision;
  const sameDraft =
    input.sentCanonical === input.currentCanonical &&
    input.sentTitle === input.currentTitle &&
    input.sentStatus === input.currentStatus;
  return { applyRevision, markBaseline: applyRevision && sameDraft };
}

export function interpretSaveConflict(input: {
  requestGeneration: number;
  latestGeneration: number;
}): "conflict" | "ignore" {
  if (input.requestGeneration < input.latestGeneration) {
    return "ignore";
  }
  return "conflict";
}
