import React from "react";
import { Metadata } from "next";
import AppNav from "@/components/AppNav";
import UploadPage from "./components/UploadPage";

export const metadata: Metadata = {
  title: "New deck | ChatPPT",
  description: "Prompt in, editable deck out.",
};

const page = () => (
  <div className="min-h-screen bg-white">
    <AppNav />
    <UploadPage />
  </div>
);

export default page;
