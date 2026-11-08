import type { GoliathUiManifest } from "@goliath/client";
import type { PlatformObjectKind } from "@goliath/ui";

/**
 * Child apps extend the host at **build time** by supplying a module with this shape.
 * No runtime Python→React loading; merge into the host bundle in the child CI.
 */
export type HostNavItem = {
  id: string;
  label: string;
  href: string;
  kind: PlatformObjectKind;
};

export type PlatformHostChildExtension = {
  appId: string;
  manifest: GoliathUiManifest;
  /** Optional extra nav leaves (fixture-only routes in P0). */
  nav?: HostNavItem[];
};

/** Example bundled with the platform host — child apps copy and replace. */
export const EXAMPLE_CHILD_EXTENSION: PlatformHostChildExtension = {
  appId: "example_child",
  manifest: {
    appId: "example_child",
    classIconOverrides: {
      "child_app/EnrollmentRow": "platform:circuit",
    },
    editorComponents: {
      "child_app/StudyManifest": "ExampleStudyManifestEditor",
    },
  },
  nav: [
    {
      id: "example",
      label: "Example child screen (stub)",
      href: "/fixture",
      kind: "config",
    },
  ],
};
