import {
  resolveClassGridPresentation,
  walkRegistryAncestry,
  type HierarchyPresentationRegistry,
  type HierarchyResolution,
} from "@goliath/platform-ui";

export type EditorResolution = HierarchyResolution;

export type ResolvedMetaEditor = {
  manifestKey: string | undefined;
  resolution: EditorResolution;
  matchedClassFqn: string | undefined;
};

export function hierarchyRegistryFromEditorComponents(
  editorComponents: Record<string, string> | undefined,
): Pick<HierarchyPresentationRegistry, "editorComponentsByClassFqn"> {
  return { editorComponentsByClassFqn: editorComponents ?? {} };
}

/** @deprecated Use {@link resolveClassGridPresentation} with a full {@link HierarchyPresentationRegistry}. */
export function resolveMetaEditorManifestKey(
  classFqn: string,
  classAncestry: readonly string[],
  editorComponents: Record<string, string> | undefined,
): ResolvedMetaEditor {
  const walk = walkRegistryAncestry(classFqn, classAncestry, editorComponents);
  return {
    manifestKey: walk.key,
    resolution: walk.resolution,
    matchedClassFqn: walk.matchedFqn,
  };
}

export { resolveClassGridPresentation };
