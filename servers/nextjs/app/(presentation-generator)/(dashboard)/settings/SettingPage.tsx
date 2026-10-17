"use client";
import React, { useState, useEffect } from "react";
import { Download, CheckCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { notify } from "@/components/ui/sonner";
import { RootState } from "@/store/store";
import { useSelector } from "react-redux";
import {
  getLLMConfigValidationError,
  handleSaveLLMConfig,
} from "@/utils/storeHelpers";
import {
  checkIfSelectedOllamaModelIsPulled,
  pullOllamaModel,
} from "@/utils/providerUtils";
import { useSearchParams } from "next/navigation";
import { isMod } from "@/lib/keys";
import { LLMConfig } from "@/types/llm_config";
import SettingSideBar from "./SettingSideBar";
import TextProvider from "./TextProvider";
import ImageProvider from "./ImageProvider";
import { IMAGE_PROVIDERS, LLM_PROVIDERS } from "@/utils/providerConstants";
import { ImagesApi } from "@/app/(presentation-generator)/services/api/images";
import { getApiUrl } from "@/utils/api";
import AccountSettings from "@/components/Auth/AccountSettings";
import UsersAdmin from "@/components/Auth/UsersAdmin";
import { AuthStatus, authApi } from "@/components/Auth/authApi";

const STOCK_IMAGE_PROVIDERS = new Set(["pexels", "pixabay"]);

// Button state interface
interface ButtonState {
  isLoading: boolean;
  isDisabled: boolean;
  text: string;
  showProgress: boolean;
  progressPercentage?: number;
  status?: string;
}

const SettingsPage = () => {
  const isSetup = useSearchParams().get("setup") === "1";
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  useEffect(() => {
    authApi<AuthStatus>("/status").then(setAuthStatus).catch(() => setAuthStatus(null));
  }, []);
  const [selectedProvider, setSelectedProvider] = useState<
    "text-provider" | "image-provider" | "session" | "users"
  >("text-provider");
  const isAccountSection = selectedProvider === "session" || selectedProvider === "users";
  const userConfigState = useSelector((state: RootState) => state.userConfig);
  const [llmConfig, setLlmConfig] = useState<LLMConfig>(
    userConfigState.llm_config
  );
  const canChangeKeys = userConfigState.can_change_keys;
  const [buttonState, setButtonState] = useState<ButtonState>({
    isLoading: false,
    isDisabled: false,
    text: "Save",
    showProgress: false,
  });

  const [downloadingModel, setDownloadingModel] = useState<{
    name: string;
    size: number | null;
    downloaded: number | null;
    status: string;
    done: boolean;
  } | null>(null);
  const [showDownloadModal, setShowDownloadModal] = useState<boolean>(false);
  const downloadAbortRef = React.useRef<AbortController | null>(null);

  const downloadProgress = React.useMemo(() => {
    if (
      downloadingModel &&
      downloadingModel.downloaded !== null &&
      downloadingModel.size !== null
    ) {
      return Math.round(
        (downloadingModel.downloaded / downloadingModel.size) * 100
      );
    }
    return 0;
  }, [downloadingModel?.downloaded, downloadingModel?.size]);

  const ensureSelectedStockProviderReady = async (): Promise<boolean> => {
    if (llmConfig.DISABLE_IMAGE_GENERATION) {
      return true;
    }

    const provider = (llmConfig.IMAGE_PROVIDER || "").toLowerCase();
    if (!STOCK_IMAGE_PROVIDERS.has(provider)) {
      return true;
    }

    const providerApiKey =
      provider === "pexels" ? llmConfig.PEXELS_API_KEY : llmConfig.PIXABAY_API_KEY;

    try {
      await ImagesApi.searchStockImages("business", 1, {
        provider,
        apiKey: providerApiKey,
        strictApiKey: true,
      });
      return true;
    } catch (error: any) {
      notify.error(
        "Cannot save settings",
        error?.message ||
        `Unable to reach ${provider} with the provided API key. Please verify your settings and try again.`
      );
      return false;
    }
  };


  const checkCurrentAuthStatus = async () => {
    try {
      const res = await fetch(getApiUrl("/api/v1/ppt/codex/auth/status"));
      if (!res.ok) {
        return false;
      }
      const data = await res.json();
      if (data.status === "authenticated") {
        return true;
      } else {
        return false;
      }
    } catch {
      return false;
    }
  };
  const handleSaveConfig = async () => {

    if (llmConfig.LLM === 'codex') {
      const isAuthenticated = await checkCurrentAuthStatus();
      if (!isAuthenticated) {
        notify.error("Sign in required", "Please sign in to ChatGPT to continue.");
        return;
      }
    }
    const validationError = getLLMConfigValidationError(llmConfig);
    if (validationError) {
      notify.warning("Cannot save settings", validationError);
      if (
        selectedProvider === "image-provider" &&
        llmConfig.LLM === "openai" &&
        !String(llmConfig.OPENAI_MODEL || "").trim()
      ) {
        setSelectedProvider("text-provider");
      }
      return;
    }

    const providerReady = await ensureSelectedStockProviderReady();
    if (!providerReady) {
      return;
    }

    try {
      setButtonState((prev) => ({
        ...prev,
        isLoading: true,
        isDisabled: true,
        text: "Saving…",
      }));
      await handleSaveLLMConfig(llmConfig);
      let ollamaModelDownloaded = false;
      if (llmConfig.LLM === "ollama" && llmConfig.OLLAMA_MODEL) {
        const isPulled = await checkIfSelectedOllamaModelIsPulled(
          llmConfig.OLLAMA_MODEL
        );
        if (!isPulled) {
          setShowDownloadModal(true);
          setDownloadingModel({
            name: llmConfig.OLLAMA_MODEL || "",
            size: null,
            downloaded: null,
            status: "pulling",
            done: false,
          });
          const downloadOutcome = await handleModelDownload();
          if (downloadOutcome === "cancelled") {
            return;
          }
          ollamaModelDownloaded = downloadOutcome === "completed";
        }
      }
      notify.success(
        ollamaModelDownloaded ? "Settings saved and model ready" : "Settings saved",
        ollamaModelDownloaded
          ? "Your configuration was saved and the Ollama model finished downloading."
          : "Your configuration was saved successfully."
      );
      setButtonState((prev) => ({
        ...prev,
        isLoading: false,
        isDisabled: false,
        text: "Save",
      }));
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Something went wrong while saving.";
      notify.error("Could not save settings", message);
      setButtonState((prev) => ({
        ...prev,
        isLoading: false,
        isDisabled: false,
        text: "Save",
      }));
    }
  };

  const handleModelDownload = async (): Promise<"completed" | "cancelled"> => {
    const ac = new AbortController();
    downloadAbortRef.current = ac;
    try {
      await pullOllamaModel(
        llmConfig.OLLAMA_MODEL!,
        setDownloadingModel,
        ac.signal
      );
      return "completed";
    } catch (e) {
      const aborted = e instanceof Error && e.name === "AbortError";
      if (aborted) {
        setDownloadingModel(null);
        setShowDownloadModal(false);
        setButtonState({
          isLoading: false,
          isDisabled: false,
          text: "Save",
          showProgress: false,
        });
        notify.info(
          "Download cancelled",
          "The Ollama model download was stopped. Your settings are already saved—you can save again to retry the download."
        );
        return "cancelled";
      }
      setDownloadingModel(null);
      setShowDownloadModal(false);
      throw e;
    } finally {
      downloadAbortRef.current = null;
    }
  };

  useEffect(() => {
    if (
      downloadingModel &&
      downloadingModel.downloaded !== null &&
      downloadingModel.size !== null
    ) {
      const percentage = Math.round(
        (downloadingModel.downloaded / downloadingModel.size) * 100
      );
      setButtonState({
        isLoading: true,
        isDisabled: true,
        text: `Downloading Model (${percentage}%)`,
        showProgress: true,
        progressPercentage: percentage,
        status: downloadingModel.status,
      });
    }

    if (downloadingModel && downloadingModel.done) {
      setTimeout(() => {
        setShowDownloadModal(false);
        setDownloadingModel(null);
      }, 2000);
    }
  }, [downloadingModel]);

  const saveRef = React.useRef(handleSaveConfig);
  useEffect(() => {
    saveRef.current = handleSaveConfig;
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isMod(e) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        saveRef.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Provider keys are locked (CAN_CHANGE_KEYS=false) or you are not an admin: your
  // account and API tokens are still yours to manage.
  if (!canChangeKeys) {
    return (
      <div>
        <h1 className="mb-5 text-xl font-semibold tracking-tight text-zinc-900">Account</h1>
        <AccountSettings authDisabled={Boolean(authStatus?.auth_disabled)} />
      </div>
    );
  }

  const textProviderKey = llmConfig.LLM || "openai";
  const textProviderLabel =
    LLM_PROVIDERS[textProviderKey]?.label || textProviderKey;
  const selectedTextModel =
    textProviderKey === "openai"
      ? llmConfig.OPENAI_MODEL
      : textProviderKey === "google"
        ? llmConfig.GOOGLE_MODEL
        : textProviderKey === "vertex"
          ? llmConfig.VERTEX_MODEL
          : textProviderKey === "azure"
            ? llmConfig.AZURE_OPENAI_MODEL
          : textProviderKey === "bedrock"
            ? llmConfig.BEDROCK_MODEL
            : textProviderKey === "openrouter"
              ? llmConfig.OPENROUTER_MODEL
              : textProviderKey === "fireworks"
                ? llmConfig.FIREWORKS_MODEL
                : textProviderKey === "together"
                  ? llmConfig.TOGETHER_MODEL
              : textProviderKey === "cerebras"
                ? llmConfig.CEREBRAS_MODEL
                : textProviderKey === "litellm"
                    ? llmConfig.LITELLM_MODEL
                    : textProviderKey === "lmstudio"
                      ? llmConfig.LMSTUDIO_MODEL
                    : textProviderKey === "anthropic"
                      ? llmConfig.ANTHROPIC_MODEL
                      : textProviderKey === "ollama"
                        ? llmConfig.OLLAMA_MODEL
                        : textProviderKey === "custom"
                          ? llmConfig.CUSTOM_MODEL
                          : textProviderKey === "codex"
                            ? llmConfig.CODEX_MODEL
                            : "";
  const textSummary = selectedTextModel
    ? `${textProviderLabel} (${selectedTextModel})`
    : textProviderLabel;

  const imageSummary = llmConfig.DISABLE_IMAGE_GENERATION
    ? "Image generation disabled"
    : llmConfig.IMAGE_PROVIDER
      ? IMAGE_PROVIDERS[llmConfig.IMAGE_PROVIDER]?.label ||
      llmConfig.IMAGE_PROVIDER
      : "No image provider";






  return (
    <div className="relative">
      <div className="mb-5 flex items-baseline gap-3">
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900">Settings</h1>
        <p className="text-xs text-zinc-500">
          {textSummary} · {imageSummary}
        </p>
      </div>
      {isSetup && (
        <p role="status" className="mb-5 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[13px] text-amber-900">
          Connect a text model to start making decks. Settings are saved to <code>chatppt.toml</code>.
        </p>
      )}
      <div className="flex gap-8">
        <SettingSideBar
          selectedProvider={selectedProvider}
          setSelectedProvider={setSelectedProvider}
          isAdmin={Boolean(authStatus?.is_admin && !authStatus?.auth_disabled)}
        />
        <div className="min-w-0 flex-1 pb-20">
          {selectedProvider === 'text-provider' && <TextProvider
            onInputChange={(value, field) => {
              setLlmConfig(prev => ({
                ...prev,
                [field]: value
              }));
            }}
            llmConfig={llmConfig}
          />}
          {selectedProvider === 'image-provider' && <ImageProvider llmConfig={llmConfig} setLlmConfig={setLlmConfig} />}
          {selectedProvider === "session" && (
            <AccountSettings authDisabled={Boolean(authStatus?.auth_disabled)} />
          )}
          {selectedProvider === "users" && <UsersAdmin currentUser={authStatus?.username ?? null} />}

        </div>
      </div>

      {!isAccountSection ? (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t border-zinc-200 bg-white/95 backdrop-blur">
          <div className="mx-auto flex max-w-[1200px] items-center justify-end gap-3 px-6 py-2.5">
            <span className="text-xs text-zinc-500">Saved to chatppt.toml · applies on the next request</span>
            <Button onClick={handleSaveConfig} disabled={buttonState.isDisabled} data-testid="save-settings">
              {buttonState.isLoading ? buttonState.text : "Save"}
            </Button>
          </div>
        </div>
      ) : null}

      {/* Download Progress Modal */}
      {showDownloadModal && downloadingModel && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white/95 backdrop-blur-md rounded-xl shadow-2xl max-w-md w-full p-6 relative">
            {/* Modal Content */}
            <div className="text-center">
              {/* Icon */}
              <div className="mb-4">
                {downloadingModel.done ? (
                  <CheckCircle className="w-12 h-12 text-green-600 mx-auto" />
                ) : (
                  <Download className="w-12 h-12 text-blue-600 mx-auto animate-pulse" />
                )}
              </div>

              {/* Title */}
              <h3 className="text-lg font-semibold text-gray-900 mb-2">
                {downloadingModel.done
                  ? "Download Complete!"
                  : "Downloading Model"}
              </h3>

              {/* Model Name */}
              <p className="text-sm text-gray-600 mb-6">
                {llmConfig.OLLAMA_MODEL}
              </p>

              {/* Progress Bar */}
              {downloadProgress > 0 && (
                <div className="mb-4">
                  <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
                    <div
                      className="bg-blue-600 h-3 rounded-full transition-all duration-300 ease-out"
                      style={{ width: `${downloadProgress}%` }}
                    />
                  </div>
                  <p className="text-sm text-gray-600 mt-2">
                    {downloadProgress}% Complete
                  </p>
                </div>
              )}

              {/* Status */}
              {downloadingModel.status && (
                <div className="flex items-center justify-center gap-2 mb-4">
                  <CheckCircle className="w-4 h-4 text-green-600" />
                  <span className="text-sm font-medium text-green-700 capitalize">
                    {downloadingModel.status}
                  </span>
                </div>
              )}

              {/* Status Message */}
              {downloadingModel.status &&
                downloadingModel.status !== "pulled" && (
                  <div className="text-xs text-gray-500">
                    {downloadingModel.status === "downloading" &&
                      "Downloading model files..."}
                    {downloadingModel.status === "verifying" &&
                      "Verifying model integrity..."}
                    {downloadingModel.status === "pulling" &&
                      "Pulling model from registry..."}
                  </div>
                )}

              {/* Download Info */}
              {downloadingModel.downloaded && downloadingModel.size && (
                <div className="mt-4 p-3 bg-gray-50 rounded-lg">
                  <div className="flex justify-between text-xs text-gray-600">
                    <span>
                      Downloaded:{" "}
                      {(downloadingModel.downloaded / 1024 / 1024).toFixed(1)}{" "}
                      MB
                    </span>
                    <span>
                      Total: {(downloadingModel.size / 1024 / 1024).toFixed(1)}{" "}
                      MB
                    </span>
                  </div>
                </div>
              )}

              {!downloadingModel.done && (
                <div className="mt-6 flex justify-center">
                  <Button
                    type="button"
                    variant="outline"
                    className="rounded-lg border-gray-300 text-gray-800 hover:bg-gray-50"
                    onClick={() => downloadAbortRef.current?.abort()}
                  >
                    Cancel download
                  </Button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SettingsPage;
