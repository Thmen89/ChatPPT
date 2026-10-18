import { useCallback, useEffect } from "react";
import { useDispatch, useSelector } from "react-redux";
import { RootState } from "@/store/store";
import { redo, undo } from "@/store/slices/undoRedoSlice";
import { isMod } from "@/lib/keys";
import { setPresentationData } from "@/store/slices/presentationGeneration";

export const usePresentationUndoRedo = () => {
  const dispatch = useDispatch();
  const undoRedoState = useSelector((state: RootState) => state.undoRedo);
  const { presentationData } = useSelector(
    (state: RootState) => state.presentationGeneration
  );

  const canUndo = undoRedoState.past.length > 0;
  const canRedo = undoRedoState.future.length > 0;

  const applySlidesSnapshot = useCallback(
    (slidesSnapshot: unknown) => {
      if (!presentationData || !Array.isArray(slidesSnapshot)) {
        return;
      }

      const clonedSlides = JSON.parse(JSON.stringify(slidesSnapshot));
      dispatch(
        setPresentationData({
          ...presentationData,
          slides: clonedSlides,
        })
      );
    },
    [dispatch, presentationData]
  );

  const onUndo = useCallback(() => {
    if (!canUndo) {
      return;
    }

    const previousState = undoRedoState.past[undoRedoState.past.length - 1];
    if (!previousState) {
      return;
    }

    dispatch(undo());
    applySlidesSnapshot(previousState.slides);
  }, [applySlidesSnapshot, canUndo, dispatch, undoRedoState.past]);

  const onRedo = useCallback(() => {
    if (!canRedo) {
      return;
    }

    const nextState = undoRedoState.future[0];
    if (!nextState) {
      return;
    }

    dispatch(redo());
    applySlidesSnapshot(nextState.slides);
  }, [applySlidesSnapshot, canRedo, dispatch, undoRedoState.future]);

  // ⌘/Ctrl+Z undoes; ⌘/Ctrl+Shift+Z and Ctrl+Y redo.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!isMod(e)) return;
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) {
        e.preventDefault();
        onUndo();
      } else if ((key === "z" && e.shiftKey) || key === "y") {
        e.preventDefault();
        onRedo();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onUndo, onRedo]);

  return { onUndo, onRedo, canUndo, canRedo };
};