import type { MetaClassField } from "@goliath/client";
import type { CatalogRef } from "./catalogRef.js";
import {
  walkRegistryAncestry,
  type HierarchyPresentationRegistry,
} from "./metaHierarchyResolver.js";
import type { ParsedFieldEditor } from "./parseFlattenedFieldSchema.js";

const GENERIC_ICON_BY_KIND: Record<string, string> = {
  string: "platform:type-string",
  int: "platform:type-integer",
  integer: "platform:type-integer",
  number: "platform:type-number",
  bool: "platform:type-boolean",
  boolean: "platform:type-boolean",
  object: "platform:type-object",
  array: "platform:type-array",
};

/** Row icon: class/type ancestry registry, then kind fallback (Delphi class-icon list pattern). */
export function resolveFieldRowIcon(
  field: MetaClassField | undefined,
  editor: ParsedFieldEditor,
  catalogTarget: CatalogRef | null,
  declaringClassAncestry: readonly string[],
  registry: HierarchyPresentationRegistry | undefined,
): string {
  const icons = registry?.iconOverridesByClassFqn;
  if (catalogTarget?.kind === "metaClass") {
    const walk = walkRegistryAncestry(catalogTarget.className, declaringClassAncestry, icons);
    if (walk.key) return walk.key;
  }
  if (field?.declaredOnClassName && icons) {
    const walk = walkRegistryAncestry(field.declaredOnClassName, declaringClassAncestry, icons);
    if (walk.key) return walk.key;
  }
  if (field?.typeName && registry?.editorComponentsByDataTypeName) {
    const dtIcon = icons?.[field.typeName];
    if (dtIcon) return dtIcon;
  }
  const kind = field?.typeKind?.toLowerCase() ?? "";
  if (kind && GENERIC_ICON_BY_KIND[kind]) return GENERIC_ICON_BY_KIND[kind];
  if (editor.mode === "nestedArray") {
    return GENERIC_ICON_BY_KIND.array ?? "platform:type-array";
  }
  if (
    editor.mode === "nestedObject" ||
    editor.mode === "typedMetaClass" ||
    editor.mode === "typedDataType"
  ) {
    return GENERIC_ICON_BY_KIND.object ?? "platform:type-object";
  }
  return GENERIC_ICON_BY_KIND.string ?? "platform:type-string";
}
