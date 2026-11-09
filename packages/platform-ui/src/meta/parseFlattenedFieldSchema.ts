export type ParsedFieldEditor =
  | {
      mode: "string" | "integer" | "number" | "boolean";
      optional: boolean;
      enumValues?: readonly string[];
    }
  | { mode: "array"; optional: boolean; itemMode: "string" | "integer" | "number" | "json" }
  | { mode: "object"; optional: boolean; propertyNames: readonly string[] }
  | { mode: "json"; optional: boolean; reason: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

function schemaAllowsNull(prop: Record<string, unknown>): boolean {
  if (prop.type === "null") return true;
  const anyOf = prop.anyOf;
  if (Array.isArray(anyOf)) {
    return anyOf.some((branch) => isRecord(branch) && branch.type === "null");
  }
  return false;
}

function primaryType(prop: Record<string, unknown>): string | undefined {
  if (typeof prop.type === "string") return prop.type;
  const anyOf = prop.anyOf;
  if (Array.isArray(anyOf)) {
    for (const branch of anyOf) {
      if (isRecord(branch) && typeof branch.type === "string" && branch.type !== "null") {
        return branch.type;
      }
    }
  }
  if (Array.isArray(prop.enum) && prop.enum.length > 0) {
    return "string";
  }
  return undefined;
}

export function parseFlattenedFieldSchema(
  prop: unknown,
  required: boolean,
): ParsedFieldEditor {
  if (!isRecord(prop)) {
    return { mode: "json", optional: !required, reason: "non-object schema node" };
  }

  const optional = !required || schemaAllowsNull(prop);

  if (Array.isArray(prop.enum) && prop.enum.every((v) => typeof v === "string" || typeof v === "number")) {
    return {
      mode: "string",
      optional,
      enumValues: prop.enum.map(String),
    };
  }

  const type = primaryType(prop);

  if (type === "string") {
    return { mode: "string", optional };
  }
  if (type === "integer") {
    return { mode: "integer", optional };
  }
  if (type === "number") {
    return { mode: "number", optional };
  }
  if (type === "boolean") {
    return { mode: "boolean", optional };
  }
  if (type === "array") {
    const items = prop.items;
    let itemMode: "string" | "integer" | "number" | "json" = "json";
    if (isRecord(items)) {
      const itemType = primaryType(items);
      if (itemType === "string") itemMode = "string";
      else if (itemType === "integer") itemMode = "integer";
      else if (itemType === "number") itemMode = "number";
    }
    if (itemMode === "json") {
      return { mode: "json", optional, reason: "unsupported array item schema" };
    }
    return { mode: "array", optional, itemMode };
  }
  if (type === "object") {
    const props = prop.properties;
    if (isRecord(props)) {
      return {
        mode: "object",
        optional,
        propertyNames: Object.keys(props).sort(),
      };
    }
    return { mode: "json", optional, reason: "object without properties" };
  }

  if (prop.$ref != null) {
    return { mode: "json", optional, reason: "unresolved $ref in flattened schema" };
  }
  if (prop.allOf != null || prop.oneOf != null) {
    return { mode: "json", optional, reason: "composition branch not expanded" };
  }

  return { mode: "json", optional, reason: "unsupported or missing type" };
}

export function propertySchemaFromFlattened(
  flattenedSchema: unknown,
  fieldName: string,
): unknown {
  if (!isRecord(flattenedSchema)) return undefined;
  const props = flattenedSchema.properties;
  if (!isRecord(props)) return undefined;
  return props[fieldName];
}
