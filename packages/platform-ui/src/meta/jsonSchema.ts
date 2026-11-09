export const SCHEMA_PROPERTY_GRID_MAX_DEPTH = 8;

export function isSchemaRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

export function schemaAllowsNull(prop: Record<string, unknown>): boolean {
  if (prop.type === "null") return true;
  const anyOf = prop.anyOf;
  if (Array.isArray(anyOf)) {
    return anyOf.some((branch) => isSchemaRecord(branch) && branch.type === "null");
  }
  return false;
}

export function primaryType(prop: Record<string, unknown>): string | undefined {
  if (typeof prop.type === "string") return prop.type;
  const anyOf = prop.anyOf;
  if (Array.isArray(anyOf)) {
    for (const branch of anyOf) {
      if (isSchemaRecord(branch) && typeof branch.type === "string" && branch.type !== "null") {
        return branch.type;
      }
    }
  }
  if (Array.isArray(prop.enum) && prop.enum.length > 0) {
    return "string";
  }
  return undefined;
}

/** Resolve local $ref against root schema `$defs` / `definitions` (flattened Meta dialect). */
export function resolveSchemaRef(
  ref: string,
  rootSchema: Record<string, unknown> | null | undefined,
): Record<string, unknown> | null {
  if (!rootSchema) return null;
  const defs = rootSchema.$defs ?? rootSchema.definitions;
  if (isSchemaRecord(defs)) {
    const direct = defs[ref];
    if (isSchemaRecord(direct)) return direct;
  }
  const match = ref.match(/^#\/(\$defs|definitions)\/(.+)$/);
  if (!match) return null;
  const bucket = rootSchema[match[1]];
  if (!isSchemaRecord(bucket)) return null;
  const node = bucket[match[2]];
  return isSchemaRecord(node) ? node : null;
}

export function resolveSchemaNode(
  node: unknown,
  rootSchema: Record<string, unknown> | null | undefined,
): Record<string, unknown> | null {
  if (!isSchemaRecord(node)) return null;
  if (typeof node.$ref === "string") {
    const resolved = resolveSchemaRef(node.$ref, rootSchema);
    return resolved ?? node;
  }
  return node;
}

export function requiredPropertySet(schema: Record<string, unknown>): Set<string> {
  const req = schema.required;
  if (!Array.isArray(req)) return new Set();
  return new Set(req.filter((n): n is string => typeof n === "string"));
}

export type SyntheticSchemaField = {
  fieldName: string;
  required: boolean;
};

export function syntheticFieldsFromSchema(
  schema: Record<string, unknown>,
  rootSchema: Record<string, unknown> | null | undefined,
): SyntheticSchemaField[] {
  const resolved = resolveSchemaNode(schema, rootSchema) ?? schema;
  const props = resolved.properties;
  if (!isSchemaRecord(props)) return [];
  const required = requiredPropertySet(resolved);
  return Object.keys(props)
    .sort()
    .map((fieldName) => ({ fieldName, required: required.has(fieldName) }));
}

export function propertySchema(
  schema: Record<string, unknown>,
  fieldName: string,
): unknown {
  const props = schema.properties;
  if (!isSchemaRecord(props)) return undefined;
  return props[fieldName];
}
