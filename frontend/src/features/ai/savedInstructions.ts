const STORAGE_KEY = "novel-workbench-instructions";
const LIMIT = 20;

export function readSavedInstructions(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .filter((item): item is string => typeof item === "string" && item.trim() !== "")
      .map((item) => item.trim())
      .slice(0, LIMIT);
  } catch {
    return [];
  }
}

export function saveInstructionText(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) {
    return readSavedInstructions();
  }
  const next = [trimmed, ...readSavedInstructions().filter((item) => item !== trimmed)].slice(0, LIMIT);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // The list still updates for this visit when storage is blocked.
  }
  return next;
}
