import React from "react";

import { requireAppSession } from "@/utils/serverAuth";
import ShortcutsDialog from "@/components/ShortcutsDialog";
import { ConfigurationInitializer } from "../ConfigurationInitializer";

export default async function Layout({ children }: { children: React.ReactNode }) {
  await requireAppSession();
  return (
    <ConfigurationInitializer>
      {children}
      <ShortcutsDialog />
    </ConfigurationInitializer>
  );
}
