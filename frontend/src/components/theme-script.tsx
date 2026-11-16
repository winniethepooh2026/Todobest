"use client";

import { useEffect } from "react";

const STORAGE_KEY = "noki-theme";

export function ThemeScript() {
  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    const theme = stored === "light" || stored === "dark" || stored === "auto"
      ? stored
      : "auto";

    const resolved =
      theme === "auto"
        ? window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light"
        : theme;

    if (resolved === "dark") {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, []);

  return null;
}
