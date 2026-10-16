import React from "react";
import * as z from "zod";
import { Rule } from "./Rule";

export const layoutId = "desk-title";
export const layoutName = "Title";
export const layoutDescription = "Opening slide: a title and a one-line subtitle.";

export const Schema = z.object({
  title: z.string().min(3).max(60).default("Quarterly review").meta({ description: "Slide title" }),
  subtitle: z.string().min(3).max(120).default("What moved and why").meta({ description: "One-line subtitle" }),
});

type Data = z.infer<typeof Schema>;

export default function Title({ data }: { data?: Partial<Data> }) {
  return (
    <div
      data-testid="desk-slide"
      className="w-full max-w-[1280px] aspect-video mx-auto overflow-hidden flex flex-col justify-center gap-6 px-[96px] bg-[#0b1220] text-[#e6e9ef]"
      style={{ fontFamily: "var(--heading-font-family, Inter)" }}
    >
      <h1 className="text-[56px] font-semibold tracking-tight">{data?.title}</h1>
      <Rule />
      <p className="text-[24px] text-[#9aa4b2]">{data?.subtitle}</p>
    </div>
  );
}
