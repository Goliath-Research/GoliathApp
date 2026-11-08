import type { GoliathUiManifest } from "./manifest.js";
import type { PlatformObjectKind } from "@goliath/ui";

/**
 * Child apps merge this module at build time (see apps/platform-host child-extension.ts).
 * P1 adds session-aware nav leaves — still no Python→React loading.
 */
export type ChildHostNavLeaf = {
  id: string;
  label: string;
  href: string;
  kind: PlatformObjectKind;
  /** When set, item is shown only if the session has this permission code (server also enforces routes). */
  requiredPermission?: string;
};

export type ChildHostExtension = {
  appId: string;
  manifest: GoliathUiManifest;
  nav?: ChildHostNavLeaf[];
};
