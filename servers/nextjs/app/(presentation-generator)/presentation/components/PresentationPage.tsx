"use client";
import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSelector } from "react-redux";
import { RootState } from "@/store/store";
import "../../utils/prism-languages";
import PresentationMode from "./PresentationMode";
import SidePanel from "./SidePanel";
import SlideContent from "./SlideContent";
import { Button } from "@/components/ui/button";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle } from "lucide-react";
import {
  usePresentationStreaming,
  usePresentationData,
  usePresentationNavigation,
  useAutoSave,
} from "../hooks";
import { PresentationPageProps } from "../types";
import { applyPresentationThemeToElement } from "../utils/applyPresentationThemeDom";

import PresentationHeader from "./PresentationHeader";
import Chat from "./Chat";
import { isMod, isTyping } from "@/lib/keys";

/** Same box as a rendered slide, for one that is still being written. */
const SlidePlaceholder = ({ index }: { index: number }) => (
  <div
    id={`slide-${index}`}
    aria-label={`Slide ${index + 1}, writing`}
    className="aspect-video w-full animate-pulse rounded-sm bg-white/70 shadow-md"
  />
);

const PresentationPage: React.FC<PresentationPageProps> = ({
  presentation_id,
}) => {
  // State management
  const [loading, setLoading] = useState(true);
  const [selectedSlide, setSelectedSlide] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isChatSending, setIsChatSending] = useState(false);
  const [isFollowModeEnabled, setIsFollowModeEnabled] = useState(true);
  const [agentFocusedSlide, setAgentFocusedSlide] = useState<number | null>(null);
  const [agentFocusEventId, setAgentFocusEventId] = useState<string | null>(null);
  const [glowingSlideIndex, setGlowingSlideIndex] = useState<number | null>(null);
  const [chatTargetedSlides, setChatTargetedSlides] = useState<number[]>([]);
  const [error, setError] = useState(false);
  const router = useRouter();
  /** Slide count from the outline (`n`), so every slide has a placeholder before it streams in. */
  const expected = Number(useSearchParams().get("n")) || 0;
  const { presentationData, isStreaming } = useSelector(
    (state: RootState) => state.presentationGeneration
  );
  // Auto-save functionality
  const { status: saveStatus, saveNow } = useAutoSave({
    debounceMs: 2000,
    enabled: !!presentationData && !isStreaming,
  });

  // Custom hooks
  const { fetchUserSlides } = usePresentationData(
    presentation_id,
    setLoading,
    setError
  );

  const {
    isPresentMode,
    stream,
    currentSlide: presentSlideFromUrl,
    handleSlideClick,
    toggleFullscreen,
    handlePresentExit,
    handleSlideChange,
  } = usePresentationNavigation(
    presentation_id,
    selectedSlide,
    setSelectedSlide,
    setIsFullscreen
  );

  // Initialize streaming
  usePresentationStreaming(
    presentation_id,
    stream,
    setLoading,
    setError,
    fetchUserSlides
  );

  /** Editor tree unmounts in present mode; remount loses inline theme CSS — re-apply from Redux. */
  useLayoutEffect(() => {
    if (isPresentMode) return;
    const theme = presentationData?.theme;
    if (!theme) return;
    const el = document.getElementById("presentation-slides-wrapper");
    applyPresentationThemeToElement(el, theme);
  }, [isPresentMode, presentationData?.theme]);

  const onSlideChange = (newSlide: number) => {
    handleSlideChange(newSlide, presentationData);
  };

  const handlePresentationChanged = useCallback(() => {
    return fetchUserSlides({ clearHistory: false });
  }, [fetchUserSlides]);

  const handleChatSendingStateChange = useCallback((sending: boolean) => {
    setIsChatSending(sending);
    if (sending) {
      setChatTargetedSlides((previous) => (previous.length === 0 ? previous : []));
      return;
    }
    setAgentFocusedSlide(null);
    setAgentFocusEventId(null);
  }, []);

  const handleAgentSlideFocus = useCallback(
    ({ slideIndex, eventId }: { slideIndex: number; eventId: string }) => {
      if (slideIndex < 0) {
        return;
      }
      setAgentFocusedSlide(slideIndex);
      setAgentFocusEventId(eventId);
      setChatTargetedSlides((previous) =>
        previous.includes(slideIndex) ? previous : [...previous, slideIndex]
      );
    },
    []
  );

  const totalSlides = presentationData?.slides?.length ?? 0;

  // J/K or arrows move between slides; E or Enter edits the slide's first field; Esc leaves it.
  const navRef = useRef({ selectedSlide, totalSlides, handleSlideClick });
  useEffect(() => {
    navRef.current = { selectedSlide, totalSlides, handleSlideClick };
  });
  useEffect(() => {
    if (isPresentMode) return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const { selectedSlide: current, totalSlides: total, handleSlideClick: go } = navRef.current;
      const slideEl = (i: number) => document.getElementById(`slide-${i}`);
      if (e.defaultPrevented || isMod(e) || e.altKey) return;
      if (isTyping(e) || total === 0 || document.querySelector("[role=dialog]")) return;
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const steps: Record<string, number> = { j: 1, ArrowDown: 1, ArrowRight: 1, k: -1, ArrowUp: -1, ArrowLeft: -1 };
      const step = steps[key];
      if (step) {
        e.preventDefault();
        go(Math.min(Math.max(current + step, 0), total - 1));
      } else if (key === "e" || (key === "Enter" && !target.closest("button, a, [role=button], [role=option]"))) {
        const field = slideEl(current)?.querySelector<HTMLElement>("[contenteditable=true]");
        if (field) {
          e.preventDefault();
          field.focus();
        }
      }
    };
    // Esc leaves a slide field; captured, because the editor swallows it.
    const onEscape = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key !== "Escape" || !target.isContentEditable) return;
      const slide = target.closest<HTMLElement>(".main-slide");
      if (!slide) return;
      target.blur();
      slide.focus({ preventScroll: true });
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keydown", onEscape, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keydown", onEscape, true);
    };
  }, [isPresentMode]);
  const highlightedSlideIndex = glowingSlideIndex;
  const targetedSlidesSet = useMemo(
    () => new Set(chatTargetedSlides),
    [chatTargetedSlides]
  );

  useEffect(() => {
    if (!isFollowModeEnabled || !isChatSending || totalSlides <= 0) {
      return;
    }
    if (agentFocusedSlide === null) {
      return;
    }

    const clampedIndex = Math.min(Math.max(agentFocusedSlide, 0), totalSlides - 1);
    if (clampedIndex !== selectedSlide) {
      handleSlideClick(clampedIndex);
    }
  }, [
    isFollowModeEnabled,
    isChatSending,
    totalSlides,
    agentFocusedSlide,
    agentFocusEventId,
    selectedSlide,
    handleSlideClick,
  ]);

  useEffect(() => {
    if (totalSlides <= 0) {
      setGlowingSlideIndex(null);
      setChatTargetedSlides([]);
      return;
    }

    if (!isChatSending) {
      if (glowingSlideIndex === null && chatTargetedSlides.length === 0) {
        return;
      }
      const clearTimer = window.setTimeout(() => {
        setGlowingSlideIndex(null);
        setChatTargetedSlides([]);
      }, 900);
      return () => window.clearTimeout(clearTimer);
    }

    // Do not show glow/scanner until chat traces identify an actual target slide.
    // This avoids the "instant scanner on send" effect before tools start editing.
    if (agentFocusedSlide === null) {
      if (glowingSlideIndex !== null) {
        setGlowingSlideIndex(null);
      }
      return;
    }

    const targetIndex = Math.min(Math.max(agentFocusedSlide, 0), totalSlides - 1);
    setGlowingSlideIndex(targetIndex);
  }, [
    isChatSending,
    totalSlides,
    selectedSlide,
    isFollowModeEnabled,
    agentFocusedSlide,
    chatTargetedSlides.length,
    glowingSlideIndex,
  ]);


  // Presentation Mode View
  if (isPresentMode) {
    return (
      <PresentationMode
        slides={presentationData?.slides!}
        currentSlide={presentSlideFromUrl}
        theme={presentationData?.theme ?? undefined}
        isFullscreen={isFullscreen}
        onFullscreenToggle={toggleFullscreen}
        onExit={handlePresentExit}
        onSlideChange={onSlideChange}
      />
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-zinc-100">
        <div
          className="bg-white border border-red-300 text-red-700 px-6 py-8 rounded-lg shadow-lg flex flex-col items-center"
          role="alert"
        >
          <AlertCircle className="w-16 h-16 mb-4 text-red-500" />
          <h2 className="text-xl font-semibold mb-2">Something went wrong</h2>
          <p className="text-center mb-4">
            We couldn't load your presentation. Please try again.
          </p>
          <div className="flex gap-2 justify-center items-center">

            <Button onClick={() => window.location.reload()}>Refresh Page</Button>
            <Button onClick={() => router.push("/upload")}>Go to Upload</Button>
          </div>
        </div>
      </div>
    );
  }

  const slides: any[] = presentationData?.slides ?? [];
  const writing = isStreaming || loading;
  const count = writing ? Math.max(expected, slides.length, slides.length ? 0 : 2) : slides.length;

  return (
    <div className="h-screen overflow-hidden">
      <div
        id="presentation-slides-wrapper"
        className="relative flex h-full flex-col overflow-hidden bg-zinc-100"
      >
        <PresentationHeader
          presentation_id={presentation_id}
          saveStatus={saveStatus}
          onSaveNow={saveNow}
          currentSlide={selectedSlide}
        />
        <div className="flex flex-1 min-h-0 gap-6 overflow-hidden">
          <div className="w-[120px] h-full shrink-0 self-start sticky top-0 pt-4">
            <SidePanel
              selectedSlide={selectedSlide}
              onSlideClick={handleSlideClick}
              presentationId={presentation_id}
              expected={expected}
              loading={loading}
            />
          </div>
          <main className="w-full min-w-0 h-full flex-1 pt-4" aria-busy={writing}>
            <div className="h-full overflow-y-auto hide-scrollbar scroll-pt-4">
              <div className="w-full max-w-[1280px] min-h-full mx-auto flex flex-col items-center gap-8 px-1 pb-8">
                {writing
                  ? Array.from({ length: count }, (_, index) => {
                      const slide = slides.find((s) => s?.index === index);
                      return slide ? (
                        <SlideContent
                          key={`${slide.type}-${index}-${slide.index}`}
                          slide={slide}
                          index={index}
                          presentationId={presentation_id}
                          selected={index === selectedSlide}
                          onSelect={() => setSelectedSlide(index)}
                        />
                      ) : (
                        <SlidePlaceholder key={`pending-${index}`} index={index} />
                      );
                    })
                  : slides.map((slide: any, index: number) => (
                      <SlideContent
                        key={`${slide.type}-${index}-${slide.index}`}
                        slide={slide}
                        index={index}
                        presentationId={presentation_id}
                        selected={index === selectedSlide}
                        onSelect={() => setSelectedSlide(index)}
                        isChatEditing={highlightedSlideIndex !== null && index === highlightedSlideIndex}
                        isChatTargeted={
                          isChatSending && highlightedSlideIndex !== index && targetedSlidesSet.has(index)
                        }
                      />
                    ))}
              </div>
            </div>
          </main>
          <div className="w-full max-w-[370px] h-full shrink-0 self-start sticky top-0">
            <Chat
              presentationId={presentation_id}
              currentSlide={selectedSlide}
              onPresentationChanged={handlePresentationChanged}
              onChatSendingStateChange={handleChatSendingStateChange}
              onFollowModeChange={setIsFollowModeEnabled}
              onAgentSlideFocus={handleAgentSlideFocus}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default PresentationPage;
