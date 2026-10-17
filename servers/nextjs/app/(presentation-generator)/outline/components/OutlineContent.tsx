"use client";
import React from "react";
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { Plus } from "lucide-react";
import type { OutlineSlide } from "@/store/slices/presentationGeneration";
import { OutlineItem } from "./OutlineItem";

interface OutlineContentProps {
  outlines: OutlineSlide[];
  isLoading: boolean;
  isStreaming: boolean;
  activeSlideIndex: number | null;
  highestActiveIndex: number;
  onDragEnd: (event: any) => void;
  onAddSlide: () => void;
}

/** Same box as an outline row, so rows replace placeholders without moving anything. */
function RowSkeleton({ index }: { index: number }) {
  return (
    <li className="flex gap-4 border-b border-zinc-100 py-4" aria-hidden>
      <span className="w-6 shrink-0 pt-0.5 text-right font-mono text-xs text-zinc-300">{index}</span>
      <div className="flex-1 space-y-2 py-0.5">
        <div className="h-3.5 w-1/3 animate-pulse rounded bg-zinc-100" />
        <div className="h-3 w-5/6 animate-pulse rounded bg-zinc-100" />
        <div className="h-3 w-2/3 animate-pulse rounded bg-zinc-100" />
      </div>
    </li>
  );
}

const OutlineContent: React.FC<OutlineContentProps> = ({
  outlines,
  isLoading,
  isStreaming,
  activeSlideIndex,
  highestActiveIndex,
  onDragEnd,
  onAddSlide,
}) => {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const busy = isLoading || isStreaming;

  return (
    <div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={outlines.map((_, i) => `slide-${i}`)} strategy={verticalListSortingStrategy}>
          <ol aria-label="Outline" className="border-t border-zinc-100">
            {outlines.map((item, index) => (
              <OutlineItem
                key={`slide-${index}`}
                sortableId={`slide-${index}`}
                index={index + 1}
                slideOutline={item}
                isStreaming={isStreaming}
                isActiveStreaming={activeSlideIndex === index}
                isStableStreaming={highestActiveIndex >= 0 && index < highestActiveIndex}
              />
            ))}
            {busy &&
              Array.from({ length: outlines.length === 0 ? 4 : 1 }).map((_, i) => (
                <RowSkeleton key={`skeleton-${i}`} index={outlines.length + i + 1} />
              ))}
          </ol>
        </SortableContext>
      </DndContext>
      {!busy && (
        <button
          type="button"
          onClick={onAddSlide}
          className="mt-3 flex items-center gap-1.5 rounded-md px-2 py-1 text-[13px] text-zinc-500 hover:text-zinc-900"
        >
          <Plus className="h-3.5 w-3.5" /> Add slide
        </button>
      )}
    </div>
  );
};

export default OutlineContent;
