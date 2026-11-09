"use client";

import { useEffect, useState } from "react";
import {
  MetaInstanceWorkbench,
  type MetaInstanceWorkbenchProps,
} from "@/components/MetaInstanceWorkbench";

/** Client-only mount so Playwright always hydrates the property grid before interaction. */
export function NestedE2eWorkbench(props: MetaInstanceWorkbenchProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) {
    return <p role="status">Loading nested property grid…</p>;
  }
  return <MetaInstanceWorkbench {...props} />;
}
