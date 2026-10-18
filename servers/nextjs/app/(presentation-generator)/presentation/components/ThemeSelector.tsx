"use client";
import React, { useState } from 'react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Palette } from 'lucide-react';

import { useDispatch } from 'react-redux';
import { updateTheme } from '@/store/slices/presentationGeneration';
import { useRouter } from 'next/navigation';
import {
    applyPresentationThemeToElement,
    clearPresentationThemeFromElement,
} from "../utils/applyPresentationThemeDom";

const ThemeSelector = ({ current_theme, themes: allThemes }: { current_theme: any, themes: any[] }) => {
    const [currentTheme, setCurrentTheme] = useState<any>(current_theme)
    const dispatch = useDispatch()
    const [isOpen, setIsOpen] = useState(false)
    const router = useRouter()
    const applyTheme = async (theme: any) => {
        const element = document.getElementById("presentation-slides-wrapper");
        if (!element) return;
        if (allThemes.length === 0) return;
        setCurrentTheme(theme);
        clearPresentationThemeFromElement(element);
        if (!theme.data?.colors?.["graph_0"]) return;
        applyPresentationThemeToElement(element, theme);
        dispatch(updateTheme(theme));
    };
    const resetTheme = async () => {
        dispatch(updateTheme(null));
        clearPresentationThemeFromElement(
            document.getElementById("presentation-slides-wrapper")
        );
    };


    return (
        <Popover open={isOpen} onOpenChange={setIsOpen}>
            <PopoverTrigger asChild>
                <button type="button" aria-expanded={isOpen} className={`flex h-7 items-center gap-1.5 rounded-md px-2 text-[13px] hover:bg-zinc-100 ${isOpen ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-600'}`}>
                    <Palette className="h-3.5 w-3.5" aria-hidden /> Theme
                </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-fit max-h-80 overflow-y-auto rounded-md p-3">
                <div className='flex justify-end gap-3 pb-2'>
                    <button type="button" className='text-xs text-zinc-500 hover:text-zinc-900' onClick={() => {
                        router.push(`/theme?tab=new-theme`)
                    }}>Customize</button>
                    <button type="button" className='text-xs text-zinc-500 hover:text-zinc-900' onClick={resetTheme}>Reset</button>
                </div>
                <div className="grid grid-cols-3 gap-3">

                    {allThemes && allThemes.length > 0 && allThemes.map((t) => (
                        <button
                            type="button"
                            key={t.id}
                            onClick={() => applyTheme(t)}
                            aria-pressed={currentTheme.id === t.id}
                            className="group relative rounded-md text-left"
                        >

                            <div className={`rounded-md border bg-white p-1 ${currentTheme.id === t.id ? 'border-[hsl(var(--ring))]' : 'border-zinc-200 group-hover:border-zinc-300'}`}>
                                <div className="rounded-lg p-2" style={{ backgroundColor: t.data.colors['background'] }}>
                                    <div className="rounded-md shadow-sm p-3" style={{ backgroundColor: t.data.colors['card'] }}>
                                        <div className="w-16 h-2 rounded-full mb-2" style={{ backgroundColor: t.data.colors['background_text'] }} />
                                        <div className="w-12 h-2 rounded-full mb-1" style={{ backgroundColor: t.data.colors['background_text'] }} />
                                        <div className="w-8 h-2 rounded-full mb-3" style={{ backgroundColor: t.data.colors['background_text'] }} />
                                        <div className="w-8 h-3 rounded-full" style={{ backgroundColor: t.data.colors['primary'] }} />
                                    </div>
                                </div>
                            </div>
                            <p className="mt-1.5 w-full truncate text-center text-xs text-zinc-700">
                                {t.name}
                            </p>
                        </button>
                    ))}
                </div>
            </PopoverContent>
        </Popover>
    )
}

export default ThemeSelector
