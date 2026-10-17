import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Trash2 } from "lucide-react";
import { RootState } from "@/store/store";
import { useDispatch, useSelector } from "react-redux";
import { deleteSlideOutline, OutlineSlide, setOutlines } from "@/store/slices/presentationGeneration";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { marked } from "marked";

interface OutlineItemProps {
  sortableId: string;
  slideOutline: OutlineSlide;
  index: number;
  isStreaming: boolean;
  isActiveStreaming?: boolean;
  isStableStreaming?: boolean;
}

const PROSE =
  "prose prose-sm max-w-none text-[13px] leading-relaxed text-zinc-700 prose-headings:text-zinc-900 prose-p:my-1 prose-ul:my-1 prose-li:my-0";

/** One outline slide: rendered markdown, click or Enter to edit, drag to reorder. */
export function OutlineItem({
  sortableId,
  index,
  slideOutline,
  isStreaming,
  isActiveStreaming = false,
  isStableStreaming = false,
}: OutlineItemProps) {
  const outlines = useSelector((state: RootState) => state.presentationGeneration.outlines);
  const dispatch = useDispatch();
  const [isEditing, setIsEditing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: sortableId,
    disabled: isStreaming,
  });

  useEffect(() => {
    if (isStreaming && isActiveStreaming) {
      document.getElementById(`outline-item-${index}`)?.scrollIntoView({ block: "nearest" });
    }
  }, [isStreaming, isActiveStreaming, index, outlines.length]);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.max(el.scrollHeight, 96)}px`;
  }, []);

  useEffect(() => {
    if (!isEditing) return;
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
    resize();
  }, [isEditing, resize]);

  // Streaming re-renders every chunk; only parse markdown when the text can still change
  // for the active row, and once for finished rows.
  const html = useMemo(() => {
    if (isStreaming && !isActiveStreaming && !isStableStreaming) return null;
    try {
      return marked.parse(slideOutline.content || "") as string;
    } catch {
      return null;
    }
  }, [isStreaming, isActiveStreaming, isStableStreaming, slideOutline.content]);

  const update = (content: string) => {
    if (isStreaming) return;
    // Keep the layout the outline call picked; only the text changes.
    dispatch(setOutlines(outlines.map((each, i) => (i === index - 1 ? { ...each, content } : each))));
  };

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`group relative flex gap-4 border-b border-zinc-100 bg-white py-4 ${isDragging ? "z-10 opacity-60" : ""}`}
    >
      <span className="w-6 shrink-0 pt-0.5 text-right font-mono text-xs text-zinc-400">{index}</span>
      <div id={`outline-item-${index}`} className="min-w-0 flex-1">
        <span className="sr-only">Slide {index}</span>
        {isStreaming ? (
          html ? (
            <div className={PROSE} dangerouslySetInnerHTML={{ __html: html }} />
          ) : (
            <p className="text-[13px] text-zinc-700">{slideOutline.content}</p>
          )
        ) : isEditing ? (
          <textarea
            ref={textareaRef}
            aria-label={`Slide ${index} outline`}
            value={slideOutline.content || ""}
            onChange={(e) => {
              update(e.target.value);
              resize();
            }}
            onBlur={() => setIsEditing(false)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                (e.target as HTMLTextAreaElement).blur();
              }
            }}
            className="w-full resize-none rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 font-mono text-[12.5px] leading-6 text-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        ) : (
          <div
            role="button"
            tabIndex={0}
            aria-label={`Edit slide ${index}`}
            onClick={() => setIsEditing(true)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === "e") {
                e.preventDefault();
                setIsEditing(true);
              }
            }}
            className="-mx-2 cursor-text rounded-md px-2 py-0.5 hover:bg-zinc-50"
          >
            {html ? (
              <div className={PROSE} dangerouslySetInnerHTML={{ __html: html }} />
            ) : (
              <p className="text-[13px] text-zinc-400">Empty slide</p>
            )}
          </div>
        )}
      </div>
      {!isStreaming && (
        <div className="flex shrink-0 items-start gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          <button
            type="button"
            {...attributes}
            {...listeners}
            aria-label={`Move slide ${index}`}
            className="cursor-grab rounded p-1 text-zinc-400 hover:text-zinc-900"
          >
            <GripVertical className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => dispatch(deleteSlideOutline({ index: index - 1 }))}
            aria-label={`Delete slide ${index}`}
            className="rounded p-1 text-zinc-400 hover:text-red-600"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </li>
  );
}
