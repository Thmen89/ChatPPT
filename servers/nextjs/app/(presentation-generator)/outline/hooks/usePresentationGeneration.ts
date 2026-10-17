import { useCallback, useState } from "react";
import { useDispatch } from "react-redux";
import { useRouter } from "next/navigation";
import { notify } from "@/components/ui/sonner";
import { clearPresentationData, OutlineSlide } from "@/store/slices/presentationGeneration";
import { PresentationGenerationApi } from "../../services/api/presentation-generation";

/**
 * Outline -> deck. The template was chosen with the prompt (stored by /create), and the
 * outline call already picked a layout per slide, so /prepare needs no structure call
 * unless the outline was reshaped (a slide added by hand has no layout yet).
 */
export const usePresentationGeneration = (presentationId: string | null, outlines: OutlineSlide[]) => {
  const dispatch = useDispatch();
  const router = useRouter();
  const [isGenerating, setIsGenerating] = useState(false);

  const generate = useCallback(async () => {
    if (!presentationId || isGenerating) return;
    if (outlines.length === 0) {
      notify.warning("Outline not ready", "Wait for the outline to finish.");
      return;
    }
    setIsGenerating(true);
    try {
      const layouts = outlines.every((o) => typeof o.layout === "number")
        ? outlines.map((o) => o.layout as number)
        : undefined;
      const prepared = await PresentationGenerationApi.presentationPrepare({
        presentation_id: presentationId,
        outlines: outlines.map(({ content }) => ({ content })),
        layouts,
      });
      dispatch(clearPresentationData());
      // The slide count lets the editor draw a placeholder per slide before any arrives.
      const n = prepared?.structure?.slides?.length ?? outlines.length;
      router.replace(`/presentation?id=${presentationId}&stream=true&n=${n}`);
    } catch (error: any) {
      console.error("Could not prepare the deck", error);
      notify.error("Could not generate", error?.message || "Something went wrong.");
      setIsGenerating(false);
    }
  }, [presentationId, outlines, isGenerating, dispatch, router]);

  return { isGenerating, generate };
};
