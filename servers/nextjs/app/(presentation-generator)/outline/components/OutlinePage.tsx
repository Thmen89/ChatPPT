"use client";

import React, { useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import { Button } from "@/components/ui/button";
import { isMod, useModLabel } from "@/lib/keys";
import OutlineContent from "./OutlineContent";
import { useOutlineStreaming } from "../hooks/useOutlineStreaming";
import { useOutlineManagement } from "../hooks/useOutlineManagement";
import { usePresentationGeneration } from "../hooks/usePresentationGeneration";

/** Review the outline, then generate. With `?auto=1` (⌘/Ctrl+Enter on the prompt) the
 * deck starts as soon as the outline is complete. */
const OutlinePage: React.FC = () => {
  const { presentation_id, outlines } = useSelector((state: RootState) => state.presentationGeneration);
  const auto = useSearchParams().get("auto") === "1";
  const mod = useModLabel();

  const streamState = useOutlineStreaming(presentation_id);
  const { handleDragEnd, handleAddSlide } = useOutlineManagement(outlines);
  const { isGenerating, generate } = usePresentationGeneration(presentation_id, outlines);
  const ready = !streamState.isStreaming && !streamState.isLoading && outlines.length > 0;

  useEffect(() => {
    if (auto && ready) generate();
    // generate changes identity with the outline; only the stream finishing should trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, ready]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter" && isMod(e) && ready) {
        e.preventDefault();
        generate();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ready, generate]);

  if (!presentation_id) {
    return (
      <div className="mx-auto max-w-[760px] px-6 pt-[12vh] text-[13px] text-zinc-600">
        <p className="mb-3">No outline in progress.</p>
        <Button asChild size="sm">
          <Link href="/upload">New deck</Link>
        </Button>
      </div>
    );
  }

  const status = isGenerating
    ? "Starting the deck…"
    : streamState.isStreaming || streamState.isLoading
      ? "Writing the outline…"
      : `${outlines.length} slides`;

  return (
    <div className="mx-auto w-full max-w-[860px] px-6 pb-16">
      <div className="sticky top-12 z-30 -mx-6 mb-4 flex items-center gap-3 border-b border-zinc-100 bg-white/95 px-6 py-3 backdrop-blur">
        <h1 className="text-[15px] font-semibold text-zinc-900">Outline</h1>
        <span role="status" aria-live="polite" className="text-xs text-zinc-500">
          {status}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <Link href="/upload">Back to prompt</Link>
          </Button>
          <Button size="sm" onClick={generate} disabled={!ready || isGenerating} data-testid="generate-deck">
            Generate deck
            <kbd className="ml-0.5 rounded bg-white/15 px-1 font-mono text-[11px] text-white/80">{mod}↵</kbd>
          </Button>
        </div>
      </div>
      <OutlineContent
        outlines={outlines}
        isLoading={streamState.isLoading}
        isStreaming={streamState.isStreaming}
        activeSlideIndex={streamState.activeSlideIndex}
        highestActiveIndex={streamState.highestActiveIndex}
        onDragEnd={handleDragEnd}
        onAddSlide={handleAddSlide}
      />
    </div>
  );
};

export default OutlinePage;
