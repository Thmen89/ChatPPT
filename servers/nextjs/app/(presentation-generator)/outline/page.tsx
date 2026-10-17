import React, { Suspense } from "react";
import { Metadata } from "next";
import AppNav from "@/components/AppNav";
import OutlinePage from "./components/OutlinePage";

export const metadata: Metadata = {
  title: "Outline | ChatPPT",
  description: "Review the outline, then generate the deck.",
};

const page = () => (
  <div className="min-h-screen bg-white">
    <AppNav />
    <Suspense>
      <OutlinePage />
    </Suspense>
  </div>
);

export default page;
