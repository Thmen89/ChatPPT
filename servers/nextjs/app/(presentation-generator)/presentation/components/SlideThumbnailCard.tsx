import React, { forwardRef } from "react";
import type { Slide } from "../../types/slide";
import { V1ContentRender } from "../../components/V1ContentRender";
import { cn } from "@/lib/utils";

interface SlideThumbnailCardProps extends React.HTMLAttributes<HTMLDivElement> {
  slide: Slide;
  index: number;
  selected: boolean;
}

const SCALE = 0.061;
const HEIGHT = 720 * SCALE;

const cardClass = "relative cursor-pointer rounded-md border bg-white p-1";

export const SlideThumbnailCard = forwardRef<HTMLDivElement, SlideThumbnailCardProps>(
  ({ slide, index, selected, className = "", style, ...props }, ref) => (
    <div
      ref={ref}
      aria-label={`Go to slide ${index + 1}`}
      aria-current={selected ? "true" : undefined}
      style={{ backgroundColor: "var(--card-color, #ffffff)", ...style }}
      className={cn(
        cardClass,
        selected ? "border-[hsl(var(--ring))] ring-1 ring-[hsl(var(--ring))]" : "border-zinc-200 hover:border-zinc-300",
        className
      )}
      {...props}
    >
      <span className="pointer-events-none absolute -left-1 top-1/2 z-50 flex h-4 min-w-4 -translate-y-1/2 items-center justify-center rounded-full border border-zinc-200 bg-white px-1 text-[10px] tabular-nums text-zinc-700">
        {index + 1}
      </span>
      <div className="relative overflow-hidden" style={{ height: HEIGHT }}>
        <div
          className="pointer-events-none absolute left-0 top-0 overflow-hidden font-syne"
          style={{ width: 1280, height: 720, transformOrigin: "top left", transform: `scale(${SCALE})` }}
        >
          <V1ContentRender slide={slide} isEditMode={true} />
        </div>
      </div>
    </div>
  )
);

SlideThumbnailCard.displayName = "SlideThumbnailCard";

/** Same box as a thumbnail, for a slide that is still being written. */
export const SlideThumbnailPlaceholder = ({ index }: { index: number }) => (
  <div className={cn(cardClass, "cursor-default border-zinc-200")} aria-hidden>
    <span className="absolute -left-1 top-1/2 z-50 flex h-4 min-w-4 -translate-y-1/2 items-center justify-center rounded-full border border-zinc-200 bg-white px-1 text-[10px] tabular-nums text-zinc-400">
      {index + 1}
    </span>
    <div className="animate-pulse rounded-sm bg-zinc-100" style={{ height: HEIGHT }} />
  </div>
);
