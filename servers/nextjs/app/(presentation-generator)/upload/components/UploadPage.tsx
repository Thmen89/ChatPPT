"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useDispatch } from "react-redux";
import { Paperclip, SlidersHorizontal, X } from "lucide-react";
import { clearOutlines, setPresentationId } from "@/store/slices/presentationGeneration";
import { setPptGenUploadState } from "@/store/slices/presentationGenUpload";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { notify } from "@/components/ui/sonner";
import { useTemplateList } from "@/app/hooks/useTemplateList";
import { isMod, useModLabel } from "@/lib/keys";
import { PresentationGenerationApi } from "../../services/api/presentation-generation";
import { LanguageType, PresentationConfig, ToneType, VerbosityType } from "../type";

const SLIDE_COUNTS = ["3", "4", "5", "6", "8", "10", "12", "15", "20", "25", "30"];
const MAX_FILES = 8;
const ACCEPT =
  ".pdf,.txt,.doc,.docx,.docm,.odt,.rtf,.ppt,.pptx,.pptm,.odp,.xls,.xlsx,.xlsm,.ods,.csv,.tsv,.jpg,.jpeg,.png,.gif,.bmp,.tiff,.webp";
const TEMPLATE_KEY = "chatppt:template";

type Mode = "outline" | "deck";

/**
 * The home screen: one prompt box. Enter writes the outline (review it, then generate);
 * ⌘/Ctrl+Enter goes straight to the deck. The template is chosen here, so the outline call
 * also picks each slide's layout.
 */
const UploadPage = () => {
  const router = useRouter();
  const dispatch = useDispatch();
  const templates = useTemplateList();
  const mod = useModLabel();
  const fileInput = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [config, setConfig] = useState<PresentationConfig>({
    template: "general",
    slides: null,
    language: LanguageType.Auto,
    prompt: "",
    tone: ToneType.Default,
    verbosity: VerbosityType.Standard,
    instructions: "",
    includeTableOfContents: false,
    includeTitleSlide: false,
    webSearch: false,
  });
  const set = <K extends keyof PresentationConfig>(key: K, value: PresentationConfig[K]) =>
    setConfig((prev) => ({ ...prev, [key]: value }));

  // Remember the last template (a per-browser convenience).
  useEffect(() => {
    try {
      const saved = localStorage.getItem(TEMPLATE_KEY);
      if (saved) set("template", saved);
    } catch {}
  }, []);
  const chooseTemplate = (id: string) => {
    set("template", id);
    try {
      localStorage.setItem(TEMPLATE_KEY, id);
    } catch {}
  };

  const addFiles = (incoming: File[]) => {
    if (incoming.length === 0) return;
    const next = [...files, ...incoming];
    if (next.length > MAX_FILES) notify.warning("Too many files", `Up to ${MAX_FILES} documents.`);
    setFiles(next.slice(0, MAX_FILES));
  };

  const start = async (mode: Mode) => {
    if (busy) return;
    if (!config.prompt.trim() && files.length === 0) {
      notify.warning("Nothing to work from", "Write a prompt or attach a document.");
      return;
    }
    if (files.length > 0 && config.language === LanguageType.Auto) {
      notify.warning("Pick a language", "Documents need a language (Options).");
      return;
    }
    try {
      if (files.length > 0) {
        setBusy("Reading documents…");
        const uploaded = await PresentationGenerationApi.uploadDoc(files);
        const decomposed = await PresentationGenerationApi.decomposeDocuments(uploaded, config.language);
        dispatch(setPptGenUploadState({ config, files: [decomposed] }));
        dispatch(clearOutlines());
        router.push("/documents-preview");
        return;
      }
      setBusy("Starting…");
      const created = await PresentationGenerationApi.createPresentation({
        content: config.prompt,
        n_slides: config.slides ? parseInt(config.slides, 10) : null,
        file_paths: [],
        language: config.language ?? "",
        tone: config.tone,
        verbosity: config.verbosity,
        instructions: config.instructions || null,
        include_table_of_contents: config.includeTableOfContents,
        include_title_slide: config.includeTitleSlide,
        web_search: config.webSearch,
        template: config.template,
      });
      dispatch(setPresentationId(created.id));
      dispatch(clearOutlines());
      router.push(mode === "deck" ? "/outline?auto=1" : "/outline");
    } catch (error: any) {
      console.error("Could not start the deck", error);
      notify.error("Could not start", error?.message || "Something went wrong.");
      setBusy(null);
    }
  };

  const onPromptKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    start(isMod(e) ? "deck" : "outline");
  };

  return (
    <div className="mx-auto w-full max-w-[760px] px-6 pt-[12vh] pb-16">
      <h1 className="mb-3 text-xl font-semibold tracking-tight text-zinc-900">New deck</h1>
      <div
        className="rounded-lg border border-zinc-200 bg-white focus-within:border-zinc-400"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          addFiles(Array.from(e.dataTransfer.files));
        }}
      >
        <label htmlFor="prompt" className="sr-only">
          What is the deck about?
        </label>
        <textarea
          id="prompt"
          data-testid="prompt-input"
          autoFocus
          rows={5}
          value={config.prompt}
          onChange={(e) => set("prompt", e.target.value)}
          onKeyDown={onPromptKey}
          placeholder="What is the deck about? Audience, key numbers, the point you want to land."
          className="block max-h-[320px] min-h-[132px] w-full resize-y rounded-t-lg bg-transparent px-4 py-3 text-[15px] leading-relaxed text-zinc-900 placeholder:text-zinc-400 focus:outline-none"
        />

        {files.length > 0 && (
          <ul className="flex flex-wrap gap-1.5 px-4 pb-2" aria-label="Attached documents">
            {files.map((file, i) => (
              <li
                key={`${file.name}-${i}`}
                className="flex items-center gap-1 rounded border border-zinc-200 bg-zinc-50 py-0.5 pl-2 pr-1 text-xs text-zinc-700"
              >
                <span className="max-w-[220px] truncate">{file.name}</span>
                <button
                  type="button"
                  aria-label={`Remove ${file.name}`}
                  onClick={() => setFiles(files.filter((_, j) => j !== i))}
                  className="rounded p-0.5 text-zinc-400 hover:text-zinc-900"
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 px-3 py-2">
          <NativeSelect
            aria-label="Template"
            data-testid="template-select"
            value={config.template}
            onChange={(e) => chooseTemplate(e.target.value)}
            className="w-[150px]"
          >
            {!templates.some((t) => t.id === config.template) && (
              <option value={config.template}>{config.template}</option>
            )}
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            aria-label="Number of slides"
            data-testid="slides-select"
            value={config.slides ?? ""}
            onChange={(e) => set("slides", e.target.value || null)}
            className="w-[112px]"
          >
            <option value="">Auto slides</option>
            {SLIDE_COUNTS.map((n) => (
              <option key={n} value={n}>
                {n} slides
              </option>
            ))}
          </NativeSelect>
          <OptionsPopover config={config} set={set} />
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []));
              e.currentTarget.value = "";
            }}
          />
          <Button type="button" variant="ghost" size="sm" onClick={() => fileInput.current?.click()}>
            <Paperclip /> Attach
          </Button>

          <div className="ml-auto flex items-center gap-2">
            {busy && (
              <span role="status" className="text-xs text-zinc-500">
                {busy}
              </span>
            )}
            <Button type="button" variant="outline" size="sm" disabled={!!busy} onClick={() => start("deck")}>
              Straight to deck <Kbd>{mod}↵</Kbd>
            </Button>
            <Button type="button" size="sm" disabled={!!busy} onClick={() => start("outline")}>
              Outline <Kbd dark>↵</Kbd>
            </Button>
          </div>
        </div>
      </div>
      <p className="mt-2 text-xs text-zinc-500">
        Enter writes an outline to review. {mod}+Enter skips it. Shift+Enter for a new line. Drop documents on
        the box to use them as sources.
      </p>
    </div>
  );
};

function Kbd({ children, dark = false }: { children: React.ReactNode; dark?: boolean }) {
  return (
    <kbd
      className={`ml-0.5 rounded px-1 font-mono text-[11px] ${dark ? "bg-white/15 text-white/80" : "bg-zinc-100 text-zinc-500"}`}
    >
      {children}
    </kbd>
  );
}

function OptionsPopover({
  config,
  set,
}: {
  config: PresentationConfig;
  set: <K extends keyof PresentationConfig>(key: K, value: PresentationConfig[K]) => void;
}) {
  const toggles: [keyof PresentationConfig, string][] = [
    ["includeTitleSlide", "Title slide"],
    ["includeTableOfContents", "Table of contents"],
    ["webSearch", "Web search"],
  ];
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="ghost" size="sm" data-testid="options-button">
          <SlidersHorizontal /> Options
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[320px] space-y-3 p-4 text-[13px]">
        <Row label="Language">
          <NativeSelect
            aria-label="Language"
            value={config.language ?? LanguageType.Auto}
            onChange={(e) => set("language", e.target.value as LanguageType)}
            className="w-[170px]"
          >
            {Object.values(LanguageType).map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </NativeSelect>
        </Row>
        <Row label="Tone">
          <NativeSelect
            aria-label="Tone"
            value={config.tone}
            onChange={(e) => set("tone", e.target.value as ToneType)}
            className="w-[170px]"
          >
            {Object.values(ToneType).map((t) => (
              <option key={t} value={t}>
                {t.replace("_", " ")}
              </option>
            ))}
          </NativeSelect>
        </Row>
        <Row label="Text per slide">
          <NativeSelect
            aria-label="Text per slide"
            value={config.verbosity}
            onChange={(e) => set("verbosity", e.target.value as VerbosityType)}
            className="w-[170px]"
          >
            {Object.values(VerbosityType).map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </NativeSelect>
        </Row>
        {toggles.map(([key, label]) => (
          <label key={key} className="flex cursor-pointer items-center justify-between">
            <span className="text-zinc-700">{label}</span>
            <input
              type="checkbox"
              checked={Boolean(config[key])}
              onChange={(e) => set(key, e.target.checked as never)}
              className="h-4 w-4 accent-zinc-900"
            />
          </label>
        ))}
        <div>
          <label htmlFor="instructions" className="mb-1 block text-zinc-700">
            Instructions
          </label>
          <textarea
            id="instructions"
            rows={3}
            value={config.instructions}
            onChange={(e) => set("instructions", e.target.value)}
            placeholder="House style, audience, things to avoid."
            className="w-full resize-none rounded-md border border-zinc-200 px-2.5 py-1.5 text-[13px] placeholder:text-zinc-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-zinc-700">{label}</span>
      {children}
    </div>
  );
}

export default UploadPage;
