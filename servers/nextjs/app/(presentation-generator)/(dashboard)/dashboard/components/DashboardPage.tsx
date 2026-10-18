"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { DashboardApi, PresentationResponse } from "@/app/(presentation-generator)/services/api/dashboard";
import { PresentationCard } from "./PresentationCard";

const byRecent = (a: PresentationResponse, b: PresentationResponse) =>
  new Date(b.updated_at ?? b.created_at).getTime() - new Date(a.updated_at ?? a.created_at).getTime();

/** Every deck, most recent first. */
const DashboardPage: React.FC = () => {
  const [presentations, setPresentations] = useState<PresentationResponse[] | null>(null);

  useEffect(() => {
    DashboardApi.getPresentations()
      .then((data: PresentationResponse[]) => setPresentations([...data].sort(byRecent)))
      .catch(() => setPresentations([]));
  }, []);

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900">
          Decks
          {presentations && presentations.length > 0 && (
            <span className="ml-2 text-[13px] font-normal text-zinc-500">{presentations.length}</span>
          )}
        </h1>
        <Button asChild size="sm">
          <Link href="/upload">New deck</Link>
        </Button>
      </div>

      {presentations === null ? (
        <div className="grid grid-cols-2 gap-6 md:grid-cols-3 lg:grid-cols-4" aria-busy="true">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i}>
              <div className="aspect-video animate-pulse rounded-md bg-zinc-100" />
              <div className="mt-2 h-3.5 w-2/3 animate-pulse rounded bg-zinc-100" />
              <div className="mt-1.5 h-3 w-1/3 animate-pulse rounded bg-zinc-100" />
            </div>
          ))}
        </div>
      ) : presentations.length === 0 ? (
        <div className="rounded-md border border-dashed border-zinc-200 px-6 py-16 text-center">
          <p className="text-[13px] text-zinc-600">No decks yet.</p>
          <Button asChild size="sm" className="mt-3">
            <Link href="/upload">New deck</Link>
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-6 md:grid-cols-3 lg:grid-cols-4">
          {presentations.map((p) => (
            <PresentationCard
              key={p.id}
              id={p.id}
              title={p.title}
              presentation={p}
              onDeleted={(id) => setPresentations((prev) => (prev ?? []).filter((x) => x.id !== id))}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default DashboardPage;
