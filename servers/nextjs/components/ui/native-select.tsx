import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/** A styled native <select>: keyboard and screen-reader behaviour for free, no JS weight. */
const NativeSelect = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <span className={cn("relative inline-flex items-center", className)}>
      <select
        ref={ref}
        className="h-7 w-full cursor-pointer appearance-none rounded-md border border-zinc-200 bg-white pl-2.5 pr-7 text-[13px] text-zinc-800 hover:border-zinc-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        {...props}
      >
        {children}
      </select>
      <ChevronDown aria-hidden className="pointer-events-none absolute right-2 h-3.5 w-3.5 text-zinc-400" />
    </span>
  )
);
NativeSelect.displayName = "NativeSelect";

export { NativeSelect };
