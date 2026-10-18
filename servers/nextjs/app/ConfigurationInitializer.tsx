'use client';

import { useEffect, useState } from 'react';
import { setCanChangeKeys, setLLMConfig } from '@/store/slices/userConfig';
import { hasValidLLMConfig, normalizeLLMConfig } from '@/utils/storeHelpers';
import { usePathname, useRouter } from 'next/navigation';
import { useDispatch } from 'react-redux';
import { checkIfSelectedOllamaModelIsPulled } from '@/utils/providerUtils';
import { LLMConfig } from '@/types/llm_config';
import { getApiUrl } from '@/utils/api';

const SETUP_PATH = '/settings';

/**
 * Loads the provider settings into the store before any app screen renders. Without a
 * usable model, every screen except Settings sends you to Settings (`?setup=1` shows why).
 */
export function ConfigurationInitializer({ children }: { children: React.ReactNode }) {
  const dispatch = useDispatch();
  const route = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const canChangeKeys = await fetchCanChangeKeys();
      dispatch(setCanChangeKeys(canChangeKeys));
      if (canChangeKeys) {
        let llmConfig: LLMConfig = {};
        try {
          // Settings live in chatppt.toml; FastAPI reads and writes it (desktop app included).
          const res = await fetch(getApiUrl('/api/v1/config'), { credentials: 'include' });
          llmConfig = res.ok ? await res.json() : {};
        } catch (e) {
          console.error('Failed to fetch user config:', e);
        }
        if (!llmConfig.LLM) llmConfig.LLM = 'openai';
        llmConfig = normalizeLLMConfig(llmConfig);
        dispatch(setLLMConfig(llmConfig));

        if (route !== SETUP_PATH && !(await isUsable(llmConfig))) {
          router.replace(`${SETUP_PATH}?setup=1`);
        }
      }
      if (!cancelled) setReady(true);
    })();
    return () => {
      cancelled = true;
    };
    // Runs once per app load; navigation between screens keeps the loaded store.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A blank page for the few milliseconds the local config takes: no logo, no spinner.
  if (!ready) return <div className="min-h-screen bg-white" aria-busy="true" />;
  return children;
}

async function fetchCanChangeKeys(): Promise<boolean> {
  try {
    if (window.electron?.getCanChangeKeys) {
      return await window.electron.getCanChangeKeys();
    }
    const res = await fetch('/api/can-change-keys');
    const data = await res.json();
    return data.canChange ?? false;
  } catch (e) {
    console.error('Failed to fetch can-change-keys:', e);
    return false;
  }
}

async function isUsable(llmConfig: LLMConfig): Promise<boolean> {
  if (!hasValidLLMConfig(llmConfig)) return false;
  if (llmConfig.LLM === 'ollama' && llmConfig.OLLAMA_MODEL) {
    return checkIfSelectedOllamaModelIsPulled(llmConfig.OLLAMA_MODEL);
  }
  if (llmConfig.LLM === 'custom') {
    try {
      const response = await fetch(getApiUrl('/api/v1/ppt/openai/models/available'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: llmConfig.CUSTOM_LLM_URL, api_key: llmConfig.CUSTOM_LLM_API_KEY }),
      });
      const data = await response.json();
      return data.includes(llmConfig.CUSTOM_MODEL);
    } catch (error) {
      console.error('Error fetching custom models:', error);
      return false;
    }
  }
  return true;
}
