import type { ChildHostExtension, ChildHostNavLeaf } from "@goliath/client";

/**
 * Child apps extend the host at **build time** by supplying a module with this shape.
 * No runtime Python→React loading; merge into the host bundle in the child CI.
 */
export type HostNavItem = ChildHostNavLeaf;

export type PlatformHostChildExtension = ChildHostExtension;

/** Example bundled with the platform host — child apps copy and replace. */
export const EXAMPLE_CHILD_EXTENSION: PlatformHostChildExtension = {
  appId: "example_child",
  manifest: {
    appId: "example_child",
    classIconOverrides: {
      "child_app/EnrollmentRow": "platform:circuit",
      "portal/NavNode": "platform:layout-grid",
      "e2e/NestedChild": "platform:layout-grid",
    },
    editorComponents: {
      "child_app/StudyManifest": "ExampleStudyManifestEditor",
      "meta/BaseDocument": "ExampleStudyManifestEditor",
      "portal/NavNode": "ExampleStudyManifestEditor",
      "e2e/NestedParent": "ExampleStudyManifestEditor",
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
