"use client";

import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { SHORTCUTS_EVENT, isTyping, useModLabel } from "@/lib/keys";

/** The `?` sheet: every keyboard shortcut, grouped by screen. Mounted once per app layout. */
export default function ShortcutsDialog() {
  const [open, setOpen] = useState(false);
  const mod = useModLabel();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "?" && !isTyping(e) && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(SHORTCUTS_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(SHORTCUTS_EVENT, onOpen);
    };
  }, []);

  const groups: [string, [string, string][]][] = [
    [
      "New deck",
      [
        ["Enter", "Write the outline"],
        [`${mod} Enter`, "Straight to the deck"],
        ["Shift Enter", "New line"],
      ],
    ],
    [
      "Outline",
      [
        [`${mod} Enter`, "Generate the deck"],
        ["Esc", "Leave the field"],
      ],
    ],
    [
      "Deck",
      [
        ["J / ↓   K / ↑", "Next / previous slide"],
        ["E or Enter", "Edit the slide's first field"],
        ["Esc", "Leave edit"],
        [`${mod} S`, "Save now"],
        [`${mod} E`, "Export PPTX"],
        [`${mod} Z  /  ${mod} Shift Z`, "Undo / redo"],
        ["P", "Present"],
      ],
    ],
    ["Anywhere", [["?", "This sheet"]]],
  ];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-md gap-0 p-0">
        <div className="border-b border-zinc-200 px-5 py-4">
          <DialogTitle className="text-sm font-semibold text-zinc-900">Keyboard shortcuts</DialogTitle>
          <DialogDescription className="mt-0.5 text-xs text-zinc-500">
            Everything works without a mouse.
          </DialogDescription>
        </div>
        <div className="max-h-[70vh] space-y-4 overflow-y-auto px-5 py-4">
          {groups.map(([title, rows]) => (
            <section key={title}>
              <h3 className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-zinc-500">{title}</h3>
              <dl className="divide-y divide-zinc-100">
                {rows.map(([keys, what]) => (
                  <div key={keys} className="flex items-center justify-between py-1.5 text-[13px]">
                    <dt className="text-zinc-700">{what}</dt>
                    <dd>
                      <kbd className="rounded border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-mono text-[11px] text-zinc-700">
                        {keys}
                      </kbd>
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
