'use client'
import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Trash2 } from "lucide-react";
import { DashboardApi } from "@/app/(presentation-generator)/services/api/dashboard";
import { notify } from "@/components/ui/sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { useFontLoader as loadFonts } from "@/app/(presentation-generator)/hooks/useFontLoad";
import SlideScale from "@/app/(presentation-generator)/components/PresentationRender";
import MarkdownRenderer from "@/components/MarkDownRender";

const COLOR_VARS: [string, string][] = [
  ["--primary-color", "primary"],
  ["--background-color", "background"],
  ["--card-color", "card"],
  ["--stroke", "stroke"],
  ["--primary-text", "primary_text"],
  ["--background-text", "background_text"],
  ...Array.from({ length: 10 }, (_, i) => [`--graph-${i}`, `graph_${i}`] as [string, string]),
];

/** A deck in the list: first-slide thumbnail, title, date. The whole card is one link. */
export const PresentationCard = ({
  id,
  title,
  presentation,
  onDeleted,
}: {
  id: string;
  title: string;
  presentation: any;
  onDeleted?: (presentationId: string) => void;
}) => {
  const thumb = useRef<HTMLDivElement>(null);
  const [confirming, setConfirming] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  // Draw the thumbnail in the deck's own theme.
  useEffect(() => {
    const el = thumb.current;
    const theme = presentation?.theme;
    if (!el || !theme?.data?.colors?.graph_0) return;
    for (const [cssVar, key] of COLOR_VARS) el.style.setProperty(cssVar, theme.data.colors[key]);
    const font = theme.data.fonts?.textFont;
    if (font?.name) {
      if (font.url) loadFonts({ [font.name]: font.url });
      for (const p of ["font-family", "--heading-font-family", "--body-font-family"]) {
        el.style.setProperty(p, `"${font.name}"`);
      }
    }
  }, [presentation?.theme]);

  const handleDelete = async () => {
    if (isDeleting) return;
    setIsDeleting(true);
    const response = await DashboardApi.deletePresentation(id);
    if (response?.success) {
      setConfirming(false);
      onDeleted?.(id);
    } else {
      notify.error("Could not delete", response?.message || "Something went wrong.");
    }
    setIsDeleting(false);
  };

  const firstSlide = presentation?.slides?.[0];
  return (
    <div className="group relative">
      <Link
        href={`/presentation?id=${id}&type=standard`}
        className="block rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <div
          ref={thumb}
          className="pointer-events-none aspect-video overflow-hidden rounded-md border border-zinc-200 bg-zinc-50 font-syne"
        >
          {firstSlide && <SlideScale slide={firstSlide} isClickable={false} />}
        </div>
        <div className="mt-2 pr-8">
          <MarkdownRenderer
            content={title || "Untitled"}
            className="mb-0 line-clamp-1 text-[13px] font-medium text-zinc-900 prose-p:my-0"
          />
          <p className="text-xs text-zinc-500">
            {new Date(presentation?.updated_at ?? presentation?.created_at).toLocaleDateString()}
            {presentation?.slides?.length ? ` · ${presentation.slides.length} slides` : ""}
          </p>
        </div>
      </Link>
      <button
        type="button"
        aria-label={`Delete ${title || "deck"}`}
        onClick={() => setConfirming(true)}
        className="absolute bottom-1 right-0 rounded p-1.5 text-zinc-400 opacity-0 hover:text-red-600 focus-visible:opacity-100 group-hover:opacity-100"
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
      <Dialog open={confirming} onOpenChange={(open) => !isDeleting && setConfirming(open)}>
        <DialogContent className="max-w-sm">
          <DialogTitle className="text-sm font-semibold">Delete this deck?</DialogTitle>
          <DialogDescription className="text-[13px]">
            &ldquo;{title}&rdquo; will be removed. This cannot be undone.
          </DialogDescription>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setConfirming(false)} disabled={isDeleting}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => void handleDelete()} disabled={isDeleting}>
              {isDeleting ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
