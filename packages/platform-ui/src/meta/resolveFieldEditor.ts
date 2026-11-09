import type { MetaClassField } from "@goliath/client";
import { parseFlattenedFieldSchema, type ParsedFieldEditor } from "./parseFlattenedFieldSchema.js";

function editorFromMetaField(field: MetaClassField): ParsedFieldEditor {
  const kind = field.typeKind?.toLowerCase();
  const typeName = field.typeName?.toLowerCase() ?? "";
  if (kind === "bool" || typeName.includes("bool")) {
    return { mode: "boolean", optional: !field.required };
  }
  if (kind === "int" || typeName.includes("int")) {
    return { mode: "integer", optional: !field.required };
  }
  if (kind === "number" || typeName.includes("number") || typeName.includes("decimal")) {
    return { mode: "number", optional: !field.required };
  }
  return { mode: "string", optional: !field.required };
}

/** Schema-first editor dispatch; Meta field metadata is fallback when flattened schema has no property. */
export function resolveFieldEditor(
  field: MetaClassField,
  flattenedSchema: unknown,
): ParsedFieldEditor {
  const props =
    flattenedSchema && typeof flattenedSchema === "object" && !Array.isArray(flattenedSchema)
      ? (flattenedSchema as { properties?: Record<string, unknown> }).properties?.[field.fieldName]
      : undefined;
  if (props != null) {
    return parseFlattenedFieldSchema(props, field.required);
  }
  return editorFromMetaField(field);
}
