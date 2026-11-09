import type { GoliathUiManifest } from "@goliath/client";
import type { HierarchyPresentationRegistry } from "@goliath/platform-ui";

export function hierarchyRegistryFromManifest(manifest: GoliathUiManifest): HierarchyPresentationRegistry {
  return {
    editorComponentsByClassFqn: manifest.editorComponents ?? {},
    iconOverridesByClassFqn: manifest.classIconOverrides ?? {},
    editorComponentsByDataTypeName: manifest.dataTypeEditorComponents ?? {},
  };
}
