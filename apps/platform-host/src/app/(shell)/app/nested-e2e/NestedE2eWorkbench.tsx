"use client";

import dynamic from "next/dynamic";
import type { MetaInstanceWorkbenchProps } from "@/components/MetaInstanceWorkbench";

const MetaInstanceWorkbench = dynamic(
  () => import("@/components/MetaInstanceWorkbench").then((m) => ({ default: m.MetaInstanceWorkbench })),
  {
    ssr: false,
    loading: () => <p role="status">Loading nested property grid…</p>,
  },
);

export function NestedE2eWorkbench(props: MetaInstanceWorkbenchProps) {
  return <MetaInstanceWorkbench {...props} />;
}
