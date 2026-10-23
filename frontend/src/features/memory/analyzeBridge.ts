export type AnalyzeRequest = {
  chapterId: string;
  revision: number;
  title: string;
  scope?: "full" | "light";
};

type AnalyzeHandler = (request: AnalyzeRequest) => void;

let analyzeHandler: AnalyzeHandler | null = null;

export function registerMemoryAnalyze(handler: AnalyzeHandler | null): void {
  analyzeHandler = handler;
}

export function requestMemoryAnalyze(request: AnalyzeRequest): void {
  analyzeHandler?.(request);
}
