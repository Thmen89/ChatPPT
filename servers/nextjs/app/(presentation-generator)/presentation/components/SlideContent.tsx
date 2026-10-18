import React, { useState } from "react";
import { Plus, Trash2, Wand2, MessageSquareText } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { notify } from "@/components/ui/sonner";
import { PresentationGenerationApi } from "../../services/api/presentation-generation";
import { RootState } from "@/store/store";
import { useDispatch, useSelector } from "react-redux";
import { deletePresentationSlide, updateSlide } from "@/store/slices/presentationGeneration";
import { addToHistory } from "@/store/slices/undoRedoSlice";
import { cn } from "@/lib/utils";
import NewSlide from "./NewSlide";
import SlideScale from "../../components/PresentationRender";

interface SlideContentProps {
  slide: any;
  index: number;
  presentationId: string;
  selected?: boolean;
  onSelect?: () => void;
  isChatEditing?: boolean;
  isChatTargeted?: boolean;
}

const toolButton =
  "flex h-7 w-7 items-center justify-center rounded text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 [&_svg]:size-3.5";

const SlideContent = ({
  slide,
  index,
  presentationId,
  selected = false,
  onSelect,
  isChatEditing = false,
  isChatTargeted = false,
}: SlideContentProps) => {
  const dispatch = useDispatch();
  const [isUpdating, setIsUpdating] = useState(false);
  const [showNewSlideSelection, setShowNewSlideSelection] = useState(false);
  const [openPopover, setOpenPopover] = useState<"edit" | "notes" | null>(null);
  const [editPrompt, setEditPrompt] = useState("");
  const { presentationData, isStreaming } = useSelector(
    (state: RootState) => state.presentationGeneration
  );

  const handleSubmit = async () => {
    if (!editPrompt.trim() || isUpdating) return;
    setIsUpdating(true);
    try {
      const response = await PresentationGenerationApi.editSlide(slide.id, editPrompt);
      if (!response) throw new Error("The server did not return an updated slide.");
      dispatch(updateSlide({ index: slide.index, slide: response }));
      setEditPrompt("");
      setOpenPopover(null);
    } catch (error: any) {
      console.error("Error in slide editing:", error);
      notify.error("Slide edit failed", error.message || "Something went wrong while editing the slide.");
    } finally {
      setIsUpdating(false);
    }
  };

  const onDeleteSlide = () => {
    if ((presentationData?.slides?.length ?? 0) <= 1) {
      notify.warning("Cannot delete slide", "A deck needs at least one slide.");
      return;
    }
    dispatch(addToHistory({ slides: presentationData?.slides, actionType: "DELETE_SLIDE" }));
    dispatch(deletePresentationSlide(slide.index));
  };

  return (
    <section
      id={`slide-${slide.index}`}
      tabIndex={-1}
      aria-label={`Slide ${index + 1}`}
      aria-current={selected ? "true" : undefined}
      onMouseDown={onSelect}
      onFocus={onSelect}
      className="main-slide group relative w-full outline-none"
    >
      <div
        data-layout={slide.layout}
        data-group={slide.layout_group}
        className={cn(
          "relative w-full rounded-sm font-syne ring-2 ring-offset-2 ring-offset-zinc-100 transition-shadow",
          selected ? "ring-[hsl(var(--ring))]" : "ring-transparent",
          isChatEditing && "chat-slide-glow",
          isChatTargeted && !isChatEditing && "chat-slide-target"
        )}
      >
        <SlideScale slide={slide} theme={presentationData?.theme || null} showEditScan={isChatEditing} />
      </div>

      {!isStreaming && (
        <div
          role="toolbar"
          aria-label={`Slide ${index + 1} actions`}
          className={cn(
            "absolute right-2 top-2 z-30 flex items-center gap-0.5 rounded-md border border-zinc-200 bg-white p-0.5 shadow-sm transition-opacity",
            openPopover
              ? "opacity-100"
              : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
          )}
        >
          <Popover open={openPopover === "edit"} onOpenChange={(o) => setOpenPopover(o ? "edit" : null)}>
            <PopoverTrigger asChild>
              <button type="button" className={toolButton} aria-label="Rewrite this slide with a prompt" title="Rewrite with a prompt">
                <Wand2 />
              </button>
            </PopoverTrigger>
            <PopoverContent side="bottom" align="end" sideOffset={6} className="z-30 w-80 rounded-md p-3">
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSubmit();
                }}
              >
                <label htmlFor={`slide-${slide.index}-prompt`} className="block text-xs font-medium text-zinc-700">
                  Rewrite slide {index + 1}
                </label>
                <Textarea
                  id={`slide-${slide.index}-prompt`}
                  value={editPrompt}
                  placeholder="e.g. tighten to three bullets, add a number"
                  className="min-h-[88px] resize-none text-[13px]"
                  disabled={isUpdating}
                  onChange={(e) => setEditPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
                    e.preventDefault();
                    handleSubmit();
                  }}
                  rows={4}
                />
                <div className="flex justify-end">
                  <Button type="submit" size="sm" disabled={isUpdating || !editPrompt.trim()}>
                    {isUpdating ? "Rewriting…" : "Rewrite ↵"}
                  </Button>
                </div>
              </form>
            </PopoverContent>
          </Popover>

          {slide?.speaker_note && (
            <Popover open={openPopover === "notes"} onOpenChange={(o) => setOpenPopover(o ? "notes" : null)}>
              <PopoverTrigger asChild>
                <button type="button" className={toolButton} aria-label="Speaker notes" title="Speaker notes">
                  <MessageSquareText />
                </button>
              </PopoverTrigger>
              <PopoverContent side="bottom" align="end" sideOffset={6} className="z-30 w-80 rounded-md p-3">
                <p className="mb-1.5 text-xs font-medium text-zinc-700">Speaker notes</p>
                <div className="max-h-[220px] overflow-auto whitespace-pre-wrap text-[13px] text-zinc-800">
                  {slide.speaker_note.trim()}
                </div>
              </PopoverContent>
            </Popover>
          )}

          <button
            type="button"
            className={toolButton}
            onClick={() => setShowNewSlideSelection(true)}
            aria-label="Add a slide below"
            title="Add a slide below"
          >
            <Plus />
          </button>
          <button type="button" className={toolButton} onClick={onDeleteSlide} aria-label="Delete slide" title="Delete slide">
            <Trash2 />
          </button>
        </div>
      )}

      {showNewSlideSelection && (
        <div
          className="fixed inset-0 z-[1000] overflow-y-auto bg-black/40 px-4 py-16"
          onClick={() => setShowNewSlideSelection(false)}
          onKeyDown={(e) => e.key === "Escape" && setShowNewSlideSelection(false)}
        >
          <div className="relative z-[1001] flex min-h-full items-start justify-center pt-10">
            <div className="w-full max-w-[675px]" onClick={(event) => event.stopPropagation()}>
              <NewSlide
                index={index}
                templateID={`${slide.layout.split(":")[0]}`}
                setShowNewSlideSelection={setShowNewSlideSelection}
                presentationId={presentationId}
              />
            </div>
          </div>
        </div>
      )}
    </section>
  );
};

export default SlideContent;
