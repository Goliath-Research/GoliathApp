export type EditorResolution = "exact" | "ancestor" | "none";

export type ResolvedMetaEditor = {
  manifestKey: string | undefined;
  resolution: EditorResolution;
  matchedClassFqn: string | undefined;
};

export function resolveMetaEditorManifestKey(
  classFqn: string,
  classAncestry: readonly string[],
  editorComponents: Record<string, string> | undefined,
): ResolvedMetaEditor {
  if (!editorComponents) {
    return { manifestKey: undefined, resolution: "none", matchedClassFqn: undefined };
  }
  const candidates = [classFqn.trim(), ...classAncestry.map((a) => a.trim())].filter(Boolean);
  const visited = new Set<string>();
  for (const fqn of candidates) {
    if (visited.has(fqn)) continue;
    visited.add(fqn);
    const key = editorComponents[fqn];
    if (key) {
      return {
        manifestKey: key,
        resolution: fqn === classFqn.trim() ? "exact" : "ancestor",
        matchedClassFqn: fqn,
      };
    }
  }
  return { manifestKey: undefined, resolution: "none", matchedClassFqn: undefined };
}
