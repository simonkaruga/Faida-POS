import { useEffect, useState } from "react";

/** This screen's look: bright, dark, or auto (dark from 18:00 to 06:00). Kept per screen. */
export type ThemeChoice = "light" | "dark" | "auto";

const KEY = "faida-theme";
const listeners = new Set<(c: ThemeChoice) => void>();

export function themeChoice(): ThemeChoice {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === "dark" || saved === "auto" ? saved : "light";
  } catch {
    return "light"; // storage unavailable: stay bright
  }
}

const isEvening = (at = new Date()) => at.getHours() >= 18 || at.getHours() < 6;

/** Puts the chosen look on the page; for auto, the one for this time of day. */
export function applyTheme(choice = themeChoice()): void {
  document.documentElement.dataset.theme = choice === "auto" ? (isEvening() ? "dark" : "light") : choice;
}

export function setThemeChoice(choice: ThemeChoice): void {
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    // the choice just won't be remembered on this screen
  }
  applyTheme(choice);
  listeners.forEach((l) => l(choice));
}

/** Call once at start-up: applies the look and keeps auto in step with the clock. */
export function startTheme(): void {
  applyTheme();
  setInterval(() => themeChoice() === "auto" && applyTheme("auto"), 60_000);
}

export function useThemeChoice(): [ThemeChoice, (c: ThemeChoice) => void] {
  const [choice, setChoice] = useState(themeChoice);
  useEffect(() => {
    listeners.add(setChoice);
    return () => void listeners.delete(setChoice);
  }, []);
  return [choice, setThemeChoice];
}
