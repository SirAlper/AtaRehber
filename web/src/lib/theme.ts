import { useCallback, useEffect, useState } from "react";

const THEME_KEY = "olr.theme";
type Theme = "light" | "dark";

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Apply the theme before the first render, so the page does not flash in the wrong colors. */
export function applyInitialTheme() {
  document.documentElement.classList.toggle("dark", (storedTheme() ?? systemTheme()) === "dark");
}

/** The user's light/dark choice, or the system setting until they choose. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => storedTheme() ?? systemTheme());
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  const toggle = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch {
        // The choice then lasts for this page view only
      }
      return next;
    });
  }, []);
  return { theme, toggle };
}
