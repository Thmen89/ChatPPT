import { useEffect, useState } from "react";

/** Keyboard helpers shared by every screen's shortcuts. */

/** ⌘ on macOS, Ctrl elsewhere. */
export function isMod(e: KeyboardEvent | React.KeyboardEvent): boolean {
  return e.metaKey || e.ctrlKey;
}

/** True when the key press belongs to a text field, so single-key shortcuts must not fire. */
export function isTyping(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null;
  if (!el) return false;
  return (
    el.isContentEditable ||
    el.tagName === "INPUT" ||
    el.tagName === "TEXTAREA" ||
    el.tagName === "SELECT" ||
    el.getAttribute("role") === "combobox"
  );
}

/** Opens the shortcut sheet (components/ShortcutsDialog.tsx) from anywhere. */
export const SHORTCUTS_EVENT = "chatppt:shortcuts";
export function openShortcuts() {
  window.dispatchEvent(new Event(SHORTCUTS_EVENT));
}

/** "⌘" or "Ctrl", for labels. */
export function modLabel(): string {
  if (typeof navigator === "undefined") return "Ctrl";
  return /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl";
}

/** `modLabel()` after mount; "Ctrl" during server render, so hydration matches. */
export function useModLabel(): string {
  const [label, setLabel] = useState("Ctrl");
  useEffect(() => setLabel(modLabel()), []);
  return label;
}
