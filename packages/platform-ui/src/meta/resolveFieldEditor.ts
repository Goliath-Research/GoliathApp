import type { MetaClassField } from "@goliath/client";
import type { HierarchyPresentationRegistry } from "./metaHierarchyResolver.js";
import {
  resolveFieldEditorFromHierarchy,
  resolveHierarchyFieldEditor,
  type HierarchyFieldResolveInput,
} from "./metaHierarchyResolver.js";
import type { ParsedFieldEditor } from "./parseFlattenedFieldSchema.js";

export type ResolveFieldEditorOptions = {
  bundledSchema?: unknown;
  declaringClassAncestry?: readonly string[];
  registry?: HierarchyPresentationRegistry;
};

function inputFromLegacy(
  field: MetaClassField,
  flattenedSchema: unknown,
  options?: ResolveFieldEditorOptions,
): HierarchyFieldResolveInput {
  return {
    field,
    flattenedSchema,
    bundledSchema: options?.bundledSchema,
    declaringClassAncestry: options?.declaringClassAncestry ?? [field.declaredOnClassName],
    registry: options?.registry,
  };
}

/** Hierarchy-first field editor resolution (class / data_type catalog, then schema constraints). */
export function resolveFieldEditor(
  field: MetaClassField,
  flattenedSchema: unknown,
  options?: ResolveFieldEditorOptions,
): ParsedFieldEditor {
  return resolveFieldEditorFromHierarchy(inputFromLegacy(field, flattenedSchema, options));
}

export function resolveFieldEditorDetailed(
  field: MetaClassField,
  flattenedSchema: unknown,
  options?: ResolveFieldEditorOptions,
) {
  return resolveHierarchyFieldEditor(inputFromLegacy(field, flattenedSchema, options));
}
