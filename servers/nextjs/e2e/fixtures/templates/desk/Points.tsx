import React from "react";
import * as z from "zod";
import { Rule } from "./Rule";

export const layoutId = "desk-points";
export const layoutName = "Points";
export const layoutDescription = "A heading and three to five short points.";

export const Schema = z.object({
  title: z.string().min(3).max(60).default("Key points").meta({ description: "Slide heading" }),
  points: z
    .array(z.string().min(3).max(100))
    .min(3)
    .max(5)
    .default(["First point", "Second point", "Third point"])
    .meta({ description: "Short points, one line each" }),
});

type Data = z.infer<typeof Schema>;

export default function Points({ data }: { data?: Partial<Data> }) {
  return (
    <div
      data-testid="desk-slide"
      className="w-full max-w-[1280px] aspect-video mx-auto overflow-hidden flex flex-col justify-center gap-8 px-[96px] bg-[#0b1220] text-[#e6e9ef]"
    >
      <h2 className="text-[40px] font-semibold">{data?.title}</h2>
      <Rule />
      <ul className="flex flex-col gap-4 text-[24px]">
        {(data?.points ?? []).map((point, index) => (
          <li key={index} className="flex gap-4">
            <span className="text-[#f5b301]">{String(index + 1).padStart(2, "0")}</span>
            <span>{point}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
