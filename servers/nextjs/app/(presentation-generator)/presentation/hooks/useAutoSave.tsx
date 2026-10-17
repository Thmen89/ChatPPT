'use client'
import { useEffect, useRef, useCallback, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { RootState } from '@/store/store';
import { PresentationGenerationApi } from '../../services/api/presentation-generation';
import { addToHistory } from '@/store/slices/undoRedoSlice';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

interface UseAutoSaveOptions {
    debounceMs?: number;
    enabled?: boolean;
}

/** Saves the deck a moment after each edit; `saveNow` (⌘S) skips the wait. */
export const useAutoSave = ({
    debounceMs = 1000,
    enabled = true,
}: UseAutoSaveOptions = {}) => {
    const dispatch = useDispatch();
    const { presentationData, isStreaming, isLoading, isLayoutLoading } = useSelector(
        (state: RootState) => state.presentationGeneration
    );

    const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const lastSavedDataRef = useRef<string>('');
    const savingRef = useRef(false);
    const [status, setStatus] = useState<SaveStatus>('idle');

    const save = useCallback(async (data: any, force = false) => {
        if (!data || savingRef.current) return;
        const serialized = JSON.stringify(data);
        if (!force && serialized === lastSavedDataRef.current) return;
        savingRef.current = true;
        setStatus('saving');
        try {
            await PresentationGenerationApi.updatePresentationContent(data);
            lastSavedDataRef.current = serialized;
            setStatus('saved');
        } catch (error) {
            console.error('Save failed:', error);
            setStatus('error');
        } finally {
            savingRef.current = false;
        }
    }, []);

    useEffect(() => {
        if (!enabled || !presentationData || isStreaming || isLoading || isLayoutLoading) return;

        dispatch(addToHistory({
            slides: presentationData.slides,
            actionType: "AUTO_SAVE"
        }));
        if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
        saveTimeoutRef.current = setTimeout(() => save(presentationData), debounceMs);

        return () => {
            if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
        };
    }, [presentationData, enabled, save, debounceMs, isLoading, isStreaming, isLayoutLoading, dispatch]);

    const saveNow = useCallback(() => {
        if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
        if (!enabled) return;
        return save(presentationData, true);
    }, [enabled, presentationData, save]);

    return { isSaving: status === 'saving', status, saveNow };
};
