import type { MetaClassField } from "@goliath/client";
import {
  catalogRefFromFieldTypeName,
  parseGoliathRef,
  type CatalogRef,
} from "./catalogRef.js";
import { isSchemaRecord, resolveSchemaNode } from "./jsonSchema.js";
import {
  parsePropertySchema,
  propertySchemaFromFlattened,
  type ParsedFieldEditor,
} from "./parseFlattenedFieldSchema.js";

export type HierarchyResolution = "exact" | "ancestor" | "dataType" | "schema" | "none";

/** Host / child-app registrations keyed by Meta class FQN and wf.data_type name. */
export type HierarchyPresentationRegistry = {
  editorComponentsByClassFqn: Record<string, string>;
  iconOverridesByClassFqn: Record<string, string>;
  editorComponentsByDataTypeName?: Record<string, string>;
};

export type RegistryWalkResult = {
  key: string | undefined;
  matchedFqn: string | undefined;
  resolution: HierarchyResolution;
};

const EMPTY_REGISTRY: HierarchyPresentationRegistry = {
  editorComponentsByClassFqn: {},
  iconOverridesByClassFqn: {},
  editorComponentsByDataTypeName: {},
};

/**
 * Walk FQN then ancestry (most specific first) for a registry map.
 * Shared by grid chrome, nested dialogs, icons, and field rows.
 */
export function walkRegistryAncestry(
  primaryFqn: string,
  ancestryNewestFirst: readonly string[],
  registry: Record<string, string> | undefined,
  resolutionExact: HierarchyResolution = "exact",
  resolutionAncestor: HierarchyResolution = "ancestor",
): RegistryWalkResult {
  if (!registry || Object.keys(registry).length === 0) {
    return { key: undefined, matchedFqn: undefined, resolution: "none" };
  }
  const candidates = [primaryFqn.trim(), ...ancestryNewestFirst.map((a) => a.trim())].filter(Boolean);
  const visited = new Set<string>();
  for (const fqn of candidates) {
    if (visited.has(fqn)) continue;
    visited.add(fqn);
    const key = registry[fqn];
    if (key) {
      return {
        key,
        matchedFqn: fqn,
        resolution: fqn === primaryFqn.trim() ? resolutionExact : resolutionAncestor,
      };
    }
  }
  return { key: undefined, matchedFqn: undefined, resolution: "none" };
}

export function resolveClassGridPresentation(
  classFqn: string,
  classAncestryNewestFirst: readonly string[],
  registry: HierarchyPresentationRegistry,
): {
  manifestKey: string | undefined;
  icon: string | undefined;
  editorResolution: HierarchyResolution;
  iconResolution: HierarchyResolution;
  matchedEditorFqn: string | undefined;
  matchedIconFqn: string | undefined;
} {
  const editor = walkRegistryAncestry(
    classFqn,
    classAncestryNewestFirst,
    registry.editorComponentsByClassFqn,
  );
  const icon = walkRegistryAncestry(
    classFqn,
    classAncestryNewestFirst,
    registry.iconOverridesByClassFqn,
  );
  return {
    manifestKey: editor.key,
    icon: icon.key,
    editorResolution: editor.resolution,
    iconResolution: icon.resolution,
    matchedEditorFqn: editor.matchedFqn,
    matchedIconFqn: icon.matchedFqn,
  };
}

export type HierarchyFieldResolveInput = {
  field: MetaClassField;
  /** Ancestry of the class where the field is declared (newest first). */
  declaringClassAncestry: readonly string[];
  flattenedSchema: unknown;
  bundledSchema?: unknown;
  registry?: HierarchyPresentationRegistry;
};

export type HierarchyFieldResolveResult = {
  editor: ParsedFieldEditor;
  catalogTarget: CatalogRef | null;
  presentation: {
    manifestKey?: string;
    icon?: string;
    matchedFqn?: string;
    resolution: HierarchyResolution;
  };
};

function bundledRoot(bundledSchema: unknown, flattenedSchema: unknown): Record<string, unknown> | null {
  if (isSchemaRecord(bundledSchema)) return bundledSchema;
  if (isSchemaRecord(flattenedSchema)) return flattenedSchema;
  return null;
}

function structuralFromCatalog(field: MetaClassField, target: CatalogRef): ParsedFieldEditor | null {
  const optional = !field.required;
  if (target.kind === "metaClass") {
    return { mode: "typedMetaClass", className: target.className, optional };
  }
  if (target.kind === "dataType") {
    const kind = field.typeKind?.toLowerCase() ?? "";
    if (kind === "object") {
      return { mode: "typedDataType", typeName: target.typeName, optional };
    }
    if (kind === "array") {
      return { mode: "typedDataType", typeName: target.typeName, optional, expectArray: true };
    }
  }
  return null;
}

/** Primitive editors bind to wf.data_type (typeKind), not raw JSON Schema `type`. */
function primitiveFromDataTypeField(
  field: MetaClassField,
  prop: unknown,
  rootSchema: Record<string, unknown> | null,
): ParsedFieldEditor {
  const optional = !field.required;
  const kind = field.typeKind?.toLowerCase() ?? "";
  const typeName = field.typeName?.toLowerCase() ?? "";

  if (prop != null && isSchemaRecord(prop)) {
    const schemaDriven = parsePropertySchema(prop, field.required, rootSchema);
    if (
      schemaDriven.mode !== "schemaless" &&
      schemaDriven.mode !== "nestedObject" &&
      schemaDriven.mode !== "nestedArray" &&
      schemaDriven.mode !== "typedMetaClass" &&
      schemaDriven.mode !== "typedDataType"
    ) {
      return schemaDriven;
    }
  }

  if (kind === "bool" || typeName === "bool" || typeName === "boolean") {
    return { mode: "boolean", optional };
  }
  if (kind === "int" || typeName === "int" || typeName === "integer") {
    return { mode: "integer", optional };
  }
  if (kind === "number" || typeName.includes("decimal") || typeName.includes("number")) {
    return { mode: "number", optional };
  }
  return { mode: "string", optional };
}

function catalogTargetFromFieldAndSchema(
  field: MetaClassField,
  prop: unknown,
  rootSchema: Record<string, unknown> | null,
): CatalogRef | null {
  const fromType = catalogRefFromFieldTypeName(field.typeName, field.typeKind);
  if (fromType && fromType.kind !== "inline") return fromType;

  if (isSchemaRecord(prop) && typeof prop.$ref === "string") {
    const parsed = parseGoliathRef(prop.$ref);
    if (parsed && parsed.kind !== "inline") return parsed;
    const resolved = resolveSchemaNode(prop, rootSchema);
    if (resolved && typeof resolved.$ref === "string") {
      const p2 = parseGoliathRef(resolved.$ref);
      if (p2 && p2.kind !== "inline") return p2;
    }
  }
  return null;
}

function arrayItemsCatalog(
  prop: unknown,
  rootSchema: Record<string, unknown> | null,
): CatalogRef | null {
  if (!isSchemaRecord(prop)) return null;
  const resolved = resolveSchemaNode(prop, rootSchema) ?? prop;
  if (resolved.type !== "array" && !resolved.items) return null;
  const items = resolveSchemaNode(resolved.items, rootSchema);
  if (!isSchemaRecord(items)) return null;
  if (typeof items.$ref === "string") {
    const parsed = parseGoliathRef(items.$ref);
    if (parsed && parsed.kind !== "inline") return parsed;
  }
  if (isSchemaRecord(items.properties)) {
    return { kind: "inline" };
  }
  return null;
}

/**
 * Single hierarchy-first resolver for field structure, nested targets, and presentation keys.
 */
export function resolveHierarchyFieldEditor(input: HierarchyFieldResolveInput): HierarchyFieldResolveResult {
  const registry = input.registry ?? EMPTY_REGISTRY;
  const root = bundledRoot(input.bundledSchema, input.flattenedSchema);
  const prop = propertySchemaFromFlattened(input.flattenedSchema, input.field.fieldName);
  const catalogTarget = catalogTargetFromFieldAndSchema(input.field, prop, root);

  if (catalogTarget?.kind === "dataType" && input.field.typeKind?.toLowerCase() === "array" && prop != null) {
    const schemaEditor = parsePropertySchema(prop, input.field.required, root);
    if (schemaEditor.mode === "nestedArray") {
      return {
        editor: schemaEditor,
        catalogTarget: arrayItemsCatalog(prop, root),
        presentation: { resolution: "schema" },
      };
    }
  }

  let presentation: HierarchyFieldResolveResult["presentation"] = {
    resolution: "none",
  };

  if (catalogTarget?.kind === "metaClass") {
    const walk = walkRegistryAncestry(
      catalogTarget.className,
      [catalogTarget.className, ...input.declaringClassAncestry],
      registry.editorComponentsByClassFqn,
    );
    presentation = {
      manifestKey: walk.key,
      matchedFqn: walk.matchedFqn,
      resolution: walk.resolution,
    };
  } else if (input.field.typeName) {
    const dtKey = registry.editorComponentsByDataTypeName?.[input.field.typeName];
    if (dtKey) {
      presentation = {
        manifestKey: dtKey,
        matchedFqn: input.field.typeName,
        resolution: "dataType",
      };
    }
  }

  if (catalogTarget) {
    const structural = structuralFromCatalog(input.field, catalogTarget);
    if (structural) {
      if (structural.mode === "typedDataType" && structural.expectArray) {
        const itemCatalog = arrayItemsCatalog(prop, root);
        if (itemCatalog?.kind === "metaClass") {
          return {
            editor: {
              mode: "nestedArray",
              optional: !input.field.required,
              itemsAreObject: true,
              itemsCatalogRef: itemCatalog,
              itemsSchema: { type: "object" },
            },
            catalogTarget: itemCatalog,
            presentation,
          };
        }
      }
      return { editor: structural, catalogTarget, presentation };
    }
  }

  if (prop != null) {
    const schemaEditor = parsePropertySchema(prop, input.field.required, root);
    if (schemaEditor.mode === "nestedObject") {
      return {
        editor: schemaEditor,
        catalogTarget: { kind: "inline" },
        presentation: { ...presentation, resolution: presentation.resolution === "none" ? "schema" : presentation.resolution },
      };
    }
    if (schemaEditor.mode === "nestedArray" && schemaEditor.itemsAreObject) {
      const itemCatalog = arrayItemsCatalog(prop, root);
      if (itemCatalog?.kind === "metaClass") {
        return {
          editor: {
            ...schemaEditor,
            itemsCatalogRef: itemCatalog,
          },
          catalogTarget: itemCatalog,
          presentation,
        };
      }
      return {
        editor: schemaEditor,
        catalogTarget: { kind: "inline" },
        presentation: { ...presentation, resolution: "schema" },
      };
    }
    if (schemaEditor.mode !== "schemaless") {
      return {
        editor: schemaEditor,
        catalogTarget: null,
        presentation: { ...presentation, resolution: "schema" },
      };
    }
  }

  const primitive = primitiveFromDataTypeField(input.field, prop, root);
  return {
    editor: primitive,
    catalogTarget: null,
    presentation: { ...presentation, resolution: "dataType" },
  };
}

/** @deprecated Prefer {@link resolveHierarchyFieldEditor}; returns structural editor only. */
export function resolveFieldEditorFromHierarchy(input: HierarchyFieldResolveInput): ParsedFieldEditor {
  return resolveHierarchyFieldEditor(input).editor;
}
