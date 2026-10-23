export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "novel-workbench-theme";
export const THEME_EVENT = "novel-theme";

export function resolveTheme(preference: ThemePreference, systemDark: boolean): ResolvedTheme {
  if (preference === "light" || preference === "dark") {
    return preference;
  }
  return systemDark ? "dark" : "light";
}

export function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      return stored;
    }
  } catch {
    // Private mode or a blocked storage API still follows the system theme.
  }
  return "system";
}

export function systemIsDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function applyTheme(preference = readPreference()): ResolvedTheme {
  const resolved = resolveTheme(preference, systemIsDark());
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themePreference = preference;
  return resolved;
}

export function setPreference(preference: ThemePreference): ResolvedTheme {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // The in-memory attribute still switches for this visit.
  }
  const resolved = applyTheme(preference);
  window.dispatchEvent(new Event(THEME_EVENT));
  return resolved;
}

export function installTheme(): () => void {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const apply = () => {
    applyTheme(readPreference());
  };
  apply();
  media.addEventListener("change", apply);
  window.addEventListener("storage", apply);
  window.addEventListener(THEME_EVENT, apply);
  return () => {
    media.removeEventListener("change", apply);
    window.removeEventListener("storage", apply);
    window.removeEventListener(THEME_EVENT, apply);
  };
}
