"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSelector } from "react-redux";
import type { RootState } from "@/store/store";
import { cn } from "@/lib/utils";
import { openShortcuts } from "@/lib/keys";

const LINKS = [
  { href: "/upload", label: "New" },
  { href: "/dashboard", label: "Decks" },
  { href: "/templates", label: "Templates" },
  { href: "/theme", label: "Themes" },
  { href: "/settings", label: "Settings" },
];

/** The one bar every screen except the editor shares. */
export default function AppNav({ children }: { children?: React.ReactNode }) {
  const pathname = usePathname();
  const canChangeKeys = useSelector((s: RootState) => s.userConfig.can_change_keys);

  return (
    <header className="sticky top-0 z-40 border-b border-zinc-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-[1200px] items-center gap-6 px-6">
        <Link href="/upload" className="text-[13px] font-semibold tracking-tight text-zinc-900">
          ChatPPT
        </Link>
        <nav aria-label="Main" className="flex items-center gap-1">
          {LINKS.map((l) => {
            const active = pathname === l.href || pathname?.startsWith(`${l.href}/`);
            return (
              <Link
                key={l.href}
                href={l.href}
                prefetch={false}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-md px-2.5 py-1 text-[13px] transition-colors",
                  active ? "bg-zinc-100 text-zinc-900" : "text-zinc-500 hover:text-zinc-900"
                )}
              >
                {/* Without key access, Settings holds only your account and API tokens. */}
                {l.href === "/settings" && !canChangeKeys ? "Account" : l.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {children}
          <button
            type="button"
            onClick={openShortcuts}
            aria-label="Keyboard shortcuts"
            title="Keyboard shortcuts (?)"
            className="flex h-7 w-7 items-center justify-center rounded-md border border-zinc-200 font-mono text-xs text-zinc-500 hover:text-zinc-900"
          >
            ?
          </button>
        </div>
      </div>
    </header>
  );
}
