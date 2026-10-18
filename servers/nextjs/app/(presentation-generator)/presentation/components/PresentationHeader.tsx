"use client";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Play, Redo2, Undo2, RotateCcw } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDispatch, useSelector } from "react-redux";
import { PresentationGenerationApi } from "../../services/api/presentation-generation";
import { RootState } from "@/store/store";
import { notify } from "@/components/ui/sonner";
import { usePresentationUndoRedo } from "../hooks/PresentationUndoRedo";
import { clearPresentationData, updateTitle } from "@/store/slices/presentationGeneration";
import { clearHistory } from "@/store/slices/undoRedoSlice";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import ThemeSelector from "./ThemeSelector";
import { DEFAULT_THEMES } from "../../(dashboard)/theme/components/ThemePanel/constants";
import ThemeApi from "../../services/api/theme";
import { Theme } from "../../services/api/types";
import { isMod, isTyping, openShortcuts, useModLabel } from "@/lib/keys";
import type { SaveStatus } from "../hooks/useAutoSave";

type Format = "pptx" | "pdf";

/** A file name the exporter and every OS accept: letters, digits, dashes; at most 40 characters. */
function exportFileName(title: string | null | undefined, format: Format): string {
  const base =
    (title || "presentation")
      .trim()
      .replace(/\.(pdf|pptx)$/i, "")
      .replace(/[^a-zA-Z0-9\s_-]+/g, "-")
      .replace(/\s+/g, "-")
      .replace(/[-_]{2,}/g, "-")
      .replace(/^[-_]+|[-_]+$/g, "")
      .slice(0, 40)
      .replace(/[-_]+$/g, "") || "presentation";
  return `${base}.${format}`;
}

function download(path: string, fileName: string) {
  const link = document.createElement("a");
  link.href = path;
  link.download = fileName;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

const STATUS_TEXT: Record<SaveStatus, string> = {
  idle: "",
  saving: "Saving…",
  saved: "Saved",
  error: "Not saved",
};

const iconButton =
  "flex h-7 w-7 items-center justify-center rounded-md text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 disabled:pointer-events-none disabled:opacity-40 [&_svg]:size-3.5";

const PresentationHeader = ({
  presentation_id,
  saveStatus,
  onSaveNow,
  currentSlide,
}: {
  presentation_id: string;
  saveStatus: SaveStatus;
  onSaveNow: () => void;
  currentSlide?: number;
}) => {
  const router = useRouter();
  const dispatch = useDispatch();
  const mod = useModLabel();
  const [exporting, setExporting] = useState<Format | null>(null);
  const [themes, setThemes] = useState<Theme[]>([]);
  const [draftTitle, setDraftTitle] = useState<string | null>(null);
  const [confirmRegenerate, setConfirmRegenerate] = useState(false);
  const titleInputRef = useRef<HTMLInputElement>(null);

  const { presentationData, isStreaming } = useSelector(
    (state: RootState) => state.presentationGeneration
  );
  const { onUndo, onRedo, canUndo, canRedo } = usePresentationUndoRedo();
  const ready = !!presentationData?.slides?.length && !isStreaming;

  useEffect(() => {
    Promise.all([ThemeApi.getThemes(), ThemeApi.getFileThemes()])
      .then(([custom, files]) => setThemes([...custom, ...files, ...DEFAULT_THEMES]))
      .catch((e) => notify.error("Could not load themes", e?.message || "Failed to load themes."));
  }, []);

  useEffect(() => {
    if (draftTitle !== null) titleInputRef.current?.select();
  }, [draftTitle !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  const commitTitle = () => {
    if (draftTitle === null || !presentationData) return;
    const next = draftTitle.trim() || presentationData.title || "Presentation";
    if (next !== presentationData.title) dispatch(updateTitle(next));
    setDraftTitle(null);
  };

  const exportAs = async (format: Format) => {
    if (!ready || exporting) return;
    const label = format.toUpperCase();
    const fileName = exportFileName(presentationData?.title, format);
    const title = fileName.replace(/\.(pdf|pptx)$/i, "");
    setExporting(format);
    const toastId = notify.loading(`Exporting ${label}`, "This can take a few seconds.");
    try {
      await PresentationGenerationApi.updatePresentationContent(presentationData);
      if (window.electron?.exportPresentation) {
        const result = await window.electron.exportPresentation(presentation_id, title, format);
        if (!result?.success) throw new Error(result?.message || "Export failed");
      } else {
        const response = await fetch("/api/export-presentation", {
          method: "POST",
          body: JSON.stringify({ format, id: presentation_id, title }),
        });
        if (!response.ok) throw new Error(`Failed to export ${label}`);
        const { path } = await response.json();
        if (!path) throw new Error("No path returned from export");
        download(path, fileName);
      }
      notify.success("Export complete", `${fileName} downloaded.`, { id: toastId });
    } catch (error) {
      console.error("Export failed:", error);
      notify.error("Export failed", "The export did not finish. Try again.", { id: toastId });
    } finally {
      setExporting(null);
    }
  };

  const present = () => {
    if (!ready) return;
    router.push(`?id=${presentation_id}&mode=present&slide=${currentSlide || 0}`);
  };

  const regenerate = () => {
    setConfirmRegenerate(false);
    dispatch(clearPresentationData());
    dispatch(clearHistory());
    router.push(`/presentation?id=${presentation_id}&stream=true&n=${presentationData?.slides?.length ?? ""}`);
  };

  // ⌘S saves now, ⌘E exports PPTX, P presents. Captured before the slide editor sees them
  // (its ⌘E would toggle inline code).
  const keysRef = useRef({ exportAs, present, onSaveNow });
  useEffect(() => {
    keysRef.current = { exportAs, present, onSaveNow };
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const key = e.key.toLowerCase();
      if (isMod(e) && !e.shiftKey && !e.altKey && key === "s") {
        e.preventDefault();
        e.stopPropagation();
        keysRef.current.onSaveNow();
      } else if (isMod(e) && !e.shiftKey && !e.altKey && key === "e") {
        e.preventDefault();
        e.stopPropagation();
        keysRef.current.exportAs("pptx");
      } else if (key === "p" && !isMod(e) && !e.altKey && !isTyping(e)) {
        e.preventDefault();
        keysRef.current.present();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  const title = presentationData?.title || "Presentation";

  return (
    <header className="sticky top-0 z-50 flex h-12 shrink-0 items-center gap-3 border-b border-zinc-200 bg-white px-4">
      <Link
        href="/dashboard"
        className="flex items-center gap-1 rounded-md px-1.5 py-1 text-[13px] text-zinc-500 hover:text-zinc-900"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        Decks
      </Link>
      <span className="h-4 w-px bg-zinc-200" aria-hidden />

      <div className="min-w-0 max-w-[480px]">
        {draftTitle !== null ? (
          <input
            ref={titleInputRef}
            value={draftTitle}
            onChange={(e) => setDraftTitle(e.target.value)}
            onBlur={commitTitle}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                commitTitle();
              } else if (e.key === "Escape") {
                e.preventDefault();
                setDraftTitle(null);
              }
            }}
            autoFocus
            aria-label="Deck title"
            className="h-7 w-full rounded-md border border-zinc-300 bg-white px-2 text-[13px] font-medium text-zinc-900 outline-none focus:border-[hsl(var(--ring))]"
          />
        ) : (
          <button
            type="button"
            onClick={() => setDraftTitle(presentationData?.title || "")}
            disabled={!ready}
            title="Rename"
            className="h-7 max-w-full truncate rounded-md px-2 text-left text-[13px] font-medium text-zinc-900 hover:bg-zinc-100 disabled:hover:bg-transparent"
          >
            {title.replace(/[#*_`]/g, "")}
          </button>
        )}
      </div>
      <span role="status" aria-live="polite" className="shrink-0 text-xs text-zinc-400">
        {isStreaming ? "Writing…" : STATUS_TEXT[saveStatus]}
      </span>

      <div className="ml-auto flex items-center gap-1">
        {presentationData?.slides?.length && !presentationData.slides[0].layout.includes("custom") ? (
          <ThemeSelector current_theme={presentationData?.theme || {}} themes={themes} />
        ) : null}
        <span className="mx-1 h-4 w-px bg-zinc-200" aria-hidden />
        <button type="button" className={iconButton} onClick={onUndo} disabled={!canUndo} aria-label="Undo" title={`Undo (${mod} Z)`}>
          <Undo2 />
        </button>
        <button type="button" className={iconButton} onClick={onRedo} disabled={!canRedo} aria-label="Redo" title={`Redo (${mod} Shift Z)`}>
          <Redo2 />
        </button>
        <button
          type="button"
          className={iconButton}
          onClick={() => setConfirmRegenerate(true)}
          disabled={!ready}
          aria-label="Regenerate deck"
          title="Regenerate deck"
        >
          <RotateCcw />
        </button>
        <button type="button" className={iconButton} onClick={present} disabled={!ready} aria-label="Present" title="Present (P)">
          <Play />
        </button>
        <button
          type="button"
          className={`${iconButton} font-mono text-xs`}
          onClick={openShortcuts}
          aria-label="Keyboard shortcuts"
          title="Keyboard shortcuts (?)"
        >
          ?
        </button>
        <span className="mx-1 h-4 w-px bg-zinc-200" aria-hidden />
        <Button variant="outline" size="sm" onClick={() => exportAs("pdf")} disabled={!ready || !!exporting}>
          {exporting === "pdf" ? "Exporting…" : "PDF"}
        </Button>
        <Button size="sm" onClick={() => exportAs("pptx")} disabled={!ready || !!exporting} title={`Export PPTX (${mod} E)`}>
          {exporting === "pptx" ? "Exporting…" : "Export PPTX"}
        </Button>
      </div>

      <Dialog open={confirmRegenerate} onOpenChange={setConfirmRegenerate}>
        <DialogContent className="max-w-sm gap-3 p-5">
          <DialogTitle className="text-sm font-semibold text-zinc-900">Regenerate the deck?</DialogTitle>
          <DialogDescription className="text-[13px] text-zinc-600">
            Every slide is written again from the outline. Your edits and undo history are lost.
          </DialogDescription>
          <DialogFooter className="gap-2">
            <Button variant="outline" size="sm" onClick={() => setConfirmRegenerate(false)}>
              Cancel
            </Button>
            <Button variant="destructive" size="sm" onClick={regenerate}>
              Regenerate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </header>
  );
};

export default PresentationHeader;
