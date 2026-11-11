import { parseGoliathRef, type CatalogRef } from "./catalogRef.js";
import {
  isSchemaRecord,
  primaryType,
  resolveSchemaNode,
  schemaAllowsNull,
} from "./jsonSchema.js";

const FALLBACK_OBJECT_SCHEMA: Record<string, unknown> = { type: "object", properties: {} };

function nestedObjectFallback(optional: boolean, schema?: Record<string, unknown>): ParsedFieldEditor {
  return {
    mode: "nestedObject",
    optional,
    objectSchema: isSchemaRecord(schema) ? schema : FALLBACK_OBJECT_SCHEMA,
  };
}

export type ParsedFieldEditor =
  | {
      mode: "string" | "integer" | "number" | "boolean";
      optional: boolean;
      enumValues?: readonly string[];
    }
  | { mode: "date"; optional: boolean; inputType: "date" | "datetime-local" }
  | { mode: "typedMetaClass"; className: string; optional: boolean }
  | { mode: "typedDataType"; typeName: string; optional: boolean; expectArray?: boolean }
  | {
      mode: "nestedObject";
      optional: boolean;
      objectSchema: Record<string, unknown>;
    }
  | {
      mode: "nestedArray";
      optional: boolean;
      itemsAreObject: boolean;
      itemsSchema: Record<string, unknown>;
      itemsCatalogRef?: CatalogRef;
      primitiveItemMode?: "string" | "integer" | "number";
    }
  | { mode: "schemaless"; optional: boolean; reason: string };

export function parsePropertySchema(
  prop: unknown,
  required: boolean,
  rootSchema: Record<string, unknown> | null | undefined,
): ParsedFieldEditor {
  if (!isSchemaRecord(prop)) {
    return nestedObjectFallback(!required);
  }

  const optional = !required || schemaAllowsNull(prop);
  const resolved = resolveSchemaNode(prop, rootSchema) ?? prop;

  if (typeof resolved.$ref === "string") {
    const catalog = parseGoliathRef(resolved.$ref);
    if (catalog?.kind === "metaClass") {
      return { mode: "typedMetaClass", className: catalog.className, optional };
    }
    if (catalog?.kind === "dataType") {
      return { mode: "typedDataType", typeName: catalog.typeName, optional };
    }
  }

  if (Array.isArray(resolved.enum) && resolved.enum.every((v) => typeof v === "string" || typeof v === "number")) {
    return {
      mode: "string",
      optional,
      enumValues: resolved.enum.map(String),
    };
  }

  const type = primaryType(resolved);

  if (type === "string") {
    const format = typeof resolved.format === "string" ? resolved.format : "";
    if (format === "date") {
      return { mode: "date", optional, inputType: "date" };
    }
    if (format === "date-time") {
      return { mode: "date", optional, inputType: "datetime-local" };
    }
    return { mode: "string", optional };
  }
  if (type === "integer") return { mode: "integer", optional };
  if (type === "number") return { mode: "number", optional };
  if (type === "boolean") return { mode: "boolean", optional };

  if (type === "array") {
    const items = resolved.items;
    const itemNode = resolveSchemaNode(items, rootSchema);
    if (!isSchemaRecord(itemNode)) {
      return {
        mode: "nestedArray",
        optional,
        itemsAreObject: false,
        itemsSchema: { type: "string" },
        primitiveItemMode: "string",
      };
    }
    const itemType = primaryType(itemNode);
    if (typeof itemNode.$ref === "string") {
      const itemCatalog = parseGoliathRef(itemNode.$ref);
      if (itemCatalog?.kind === "metaClass") {
        return {
          mode: "nestedArray",
          optional,
          itemsAreObject: true,
          itemsSchema: itemNode,
          itemsCatalogRef: itemCatalog,
        };
      }
    }
    if (itemType === "object" || isSchemaRecord(itemNode.properties)) {
      return {
        mode: "nestedArray",
        optional,
        itemsAreObject: true,
        itemsSchema: itemNode,
      };
    }
    if (itemType === "string") {
      return { mode: "nestedArray", optional, itemsAreObject: false, itemsSchema: itemNode, primitiveItemMode: "string" };
    }
    if (itemType === "integer") {
      return { mode: "nestedArray", optional, itemsAreObject: false, itemsSchema: itemNode, primitiveItemMode: "integer" };
    }
    if (itemType === "number") {
      return { mode: "nestedArray", optional, itemsAreObject: false, itemsSchema: itemNode, primitiveItemMode: "number" };
    }
    return {
      mode: "nestedArray",
      optional,
      itemsAreObject: false,
      itemsSchema: itemNode,
      primitiveItemMode: "string",
    };
  }

  if (type === "object" || isSchemaRecord(resolved.properties)) {
    return { mode: "nestedObject", optional, objectSchema: resolved };
  }

  if (resolved.allOf != null || resolved.oneOf != null) {
    return nestedObjectFallback(optional, resolved);
  }

  return nestedObjectFallback(optional);
}

export function parseFlattenedFieldSchema(
  prop: unknown,
  required: boolean,
  rootSchema?: Record<string, unknown> | null,
): ParsedFieldEditor {
  return parsePropertySchema(prop, required, rootSchema ?? null);
}

export function propertySchemaFromFlattened(
  flattenedSchema: unknown,
  fieldName: string,
): unknown {
  if (!isSchemaRecord(flattenedSchema)) return undefined;
  const props = flattenedSchema.properties;
  if (!isSchemaRecord(props)) return undefined;
  return props[fieldName];
}
