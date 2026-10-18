import React from "react";
import AppNav from "@/components/AppNav";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-white">
      <AppNav />
      <main className="mx-auto w-full max-w-[1200px] px-6 py-6">{children}</main>
    </div>
  );
}
