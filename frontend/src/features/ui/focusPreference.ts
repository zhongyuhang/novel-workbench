export const FOCUS_STORAGE_KEY = "novel-workbench-focus";

export function readFocusMode(): boolean {
  try {
    return localStorage.getItem(FOCUS_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeFocusMode(enabled: boolean): void {
  try {
    localStorage.setItem(FOCUS_STORAGE_KEY, enabled ? "1" : "0");
  } catch {
    // The current visit still toggles when storage is blocked.
  }
}
