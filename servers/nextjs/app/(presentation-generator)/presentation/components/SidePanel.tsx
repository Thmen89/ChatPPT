"use client";
import React, { useState } from "react";
import { createPortal } from "react-dom";
import { Plus } from "lucide-react";
import { useDispatch, useSelector } from "react-redux";
import { RootState } from "@/store/store";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { setPresentationData } from "@/store/slices/presentationGeneration";
import { SortableSlide } from "./SortableSlide";
import NewSlide from "./NewSlide";
import { SlideThumbnailCard, SlideThumbnailPlaceholder } from "./SlideThumbnailCard";

interface SidePanelProps {
  selectedSlide: number;
  onSlideClick: (index: number) => void;
  presentationId: string;
  /** Slides the stream will deliver; the missing ones show as placeholders. */
  expected: number;
  loading: boolean;
}

const SidePanel = ({
  selectedSlide,
  onSlideClick,
  presentationId,
  expected,
  loading,
}: SidePanelProps) => {
  const [showNewSlideSelection, setShowNewSlideSelection] = useState(false);

  const { presentationData, isStreaming } = useSelector(
    (state: RootState) => state.presentationGeneration
  );

  const dispatch = useDispatch();

  const lastSlideIndex = presentationData?.slides?.length
    ? presentationData.slides.length - 1
    : 0;
  const lastSlideTemplateId = presentationData?.slides?.[lastSlideIndex]?.layout
    ? presentationData.slides[lastSlideIndex].layout.split(":")[0]
    : "";

  const handleAddSlideClick = () => {
    if (!presentationData?.slides?.length || isStreaming) return;
    setShowNewSlideSelection(true);
  };

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8, // Start drag after moving 8px
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = (event: any) => {
    const { active, over } = event;

    if (!active || !over || !presentationData?.slides) return;

    if (active.id !== over.id) {
      // Find the indices of the dragged and target items
      const oldIndex = presentationData?.slides.findIndex(
        (item: any) => item.id === active.id
      );
      const newIndex = presentationData?.slides.findIndex(
        (item: any) => item.id === over.id
      );

      // Reorder the array
      const reorderedArray = arrayMove(
        presentationData?.slides,
        oldIndex,
        newIndex
      );

      // Update indices of all slides
      const updatedArray = reorderedArray.map((slide: any, index: number) => ({
        ...slide,
        index: index,
      }));

      // Update the store with new order and indices
      dispatch(
        setPresentationData({ ...presentationData, slides: updatedArray })
      );
    }
  };

  const slides: any[] = presentationData?.slides ?? [];
  const writing = isStreaming || loading;
  if (!slides.length && !(writing && expected > 0)) {
    return null;
  }
  const count = writing ? Math.max(expected, slides.length) : slides.length;

  const shouldShowNewSlideModal =
    showNewSlideSelection &&
    lastSlideTemplateId &&
    typeof document !== "undefined";

  const newSlideModal = shouldShowNewSlideModal
    ? createPortal(
        <div
          className="fixed inset-0 z-[1000] overflow-y-auto bg-black/50 px-4 py-16"
          onClick={() => setShowNewSlideSelection(false)}
        >
          <div className="relative z-[1001] flex min-h-full items-start justify-center pt-10">
            <div
              className="w-full max-w-[675px]"
              onClick={(event) => event.stopPropagation()}
            >
              <NewSlide
                index={lastSlideIndex}
                templateID={lastSlideTemplateId}
                setShowNewSlideSelection={setShowNewSlideSelection}
                presentationId={presentationId}
              />
            </div>
          </div>
        </div>,
        document.body
      )
    : null;

  return (
    <nav aria-label="Slides" className="h-full w-[120px] px-4">
      <div
        className={`
          relative  h-full z-50 xl:z-auto 
          transition-all duration-300 ease-in-out
        `}
      >
        <div className="w-full h-full hide-scrollbar overflow-hidden slide-theme flex flex-col">
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <div className="overflow-y-auto w-full hide-scrollbar min-h-0 flex-1 space-y-3.5">
              {writing ? (
                Array.from({ length: count }, (_, index) => {
                  const slide = slides.find((s) => s?.index === index);
                  return slide ? (
                    <SlideThumbnailCard
                      key={`${slide.id}-${index}`}
                      slide={slide}
                      index={index}
                      selected={selectedSlide === index}
                      onClick={() => onSlideClick(index)}
                    />
                  ) : (
                    <SlideThumbnailPlaceholder key={`pending-${index}`} index={index} />
                  );
                })
              ) : (
                <SortableContext
                  items={
                    presentationData?.slides.map(
                      (slide: any) => slide.id || `${slide.index}`
                    ) || []
                  }
                  strategy={verticalListSortingStrategy}
                >
                  {presentationData &&
                    presentationData?.slides.map(
                      (slide: any, index: number) => (
                        <SortableSlide
                          key={`${slide.id}-${index}`}
                          slide={slide}
                          index={index}
                          selectedSlide={selectedSlide}
                          onSlideClick={onSlideClick}
                        />
                      )
                    )}
                </SortableContext>
              )}
            </div>
          </DndContext>
          <button
            type="button"
            onClick={handleAddSlideClick}
            disabled={writing}
            className="mt-2 flex w-full items-center justify-center gap-1 rounded-md border border-dashed border-zinc-300 py-2 text-[11px] text-zinc-600 hover:border-zinc-400 hover:text-zinc-900 disabled:opacity-40"
          >
            <Plus className="h-3 w-3" aria-hidden />
            Add
          </button>
        </div>
      </div>
      {newSlideModal}
    </nav>
  );
};

export default SidePanel;
