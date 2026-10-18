import React from "react";

// A helper module: no layoutId, so it is not a layout; layouts import it as "./Rule".
export function Rule() {
  return <div data-testid="desk-rule" className="h-[3px] w-24 bg-[#f5b301]" />;
}
