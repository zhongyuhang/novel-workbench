import { useEffect, useState } from "react";
import {
  readPreference,
  setPreference,
  THEME_EVENT,
  type ThemePreference,
} from "../theme.ts";

const OPTIONS: Array<{ value: ThemePreference; label: string }> = [
  { value: "system", label: "系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "赛博" },
];

export function ThemeSwitcher() {
  const [preference, setLocal] = useState<ThemePreference>(() => readPreference());

  useEffect(() => {
    const sync = () => {
      setLocal(readPreference());
    };
    window.addEventListener(THEME_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(THEME_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return (
    <div className="theme-switch" role="group" aria-label="颜色模式">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          className="ghost"
          type="button"
          aria-pressed={preference === option.value}
          onClick={() => {
            setPreference(option.value);
            setLocal(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
