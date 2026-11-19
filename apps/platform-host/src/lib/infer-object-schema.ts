/**
 * Read-only schema inferred from a value (for viewing documents that have no registered type).
 * Never used for editing: editors need a registered schema.
 */
export function inferObjectSchema(value: unknown): Record<string, unknown> {
  return inferSchema(value, 0);
}

function inferSchema(value: unknown, depth: number): Record<string, unknown> {
  if (Array.isArray(value)) {
    return { type: "array", items: depth < 6 && value.length ? inferSchema(value[0], depth + 1) : {} };
  }
  if (value && typeof value === "object") {
    const props: Record<string, unknown> = {};
    if (depth < 6) {
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) props[k] = inferSchema(v, depth + 1);
    }
    return { type: "object", properties: props };
  }
  if (typeof value === "boolean") return { type: "boolean" };
  if (typeof value === "number") return { type: Number.isInteger(value) ? "integer" : "number" };
  return { type: "string" };
}
