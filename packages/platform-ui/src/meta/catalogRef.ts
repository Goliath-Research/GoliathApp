/** Catalog URI conventions from `Meta.fn_type_schema_uri` / `Meta.fn_class_schema_uri`. */

export const META_CLASS_CATALOG_PREFIX = "meta/class/";
export const GOLIATH_META_CLASS_PREFIX = "goliath:meta/class/";
export const GOLIATH_TYPE_PREFIX = "goliath:type/";

export type CatalogRef =
  | { kind: "metaClass"; className: string }
  | { kind: "dataType"; typeName: string }
  | { kind: "inline" };

export function parseGoliathRef(ref: string): CatalogRef | null {
  const trimmed = ref.trim();
  if (trimmed.startsWith(GOLIATH_META_CLASS_PREFIX)) {
    return { kind: "metaClass", className: trimmed.slice(GOLIATH_META_CLASS_PREFIX.length) };
  }
  if (trimmed.startsWith(GOLIATH_TYPE_PREFIX)) {
    return { kind: "dataType", typeName: trimmed.slice(GOLIATH_TYPE_PREFIX.length) };
  }
  if (trimmed.startsWith(META_CLASS_CATALOG_PREFIX)) {
    return { kind: "metaClass", className: trimmed.slice(META_CLASS_CATALOG_PREFIX.length) };
  }
  return null;
}

export function catalogRefFromFieldTypeName(
  typeName: string | null | undefined,
  typeKind?: string | null,
): CatalogRef | null {
  if (!typeName) return null;
  const parsed = parseGoliathRef(typeName);
  if (parsed && parsed.kind !== "inline") return parsed;
  const kind = typeKind?.toLowerCase() ?? "";
  if (kind === "object" || kind === "array") {
    return { kind: "dataType", typeName };
  }
  return null;
}

export function resolveBundledDefRef(
  ref: string,
  bundledSchema: Record<string, unknown> | null | undefined,
): Record<string, unknown> | null {
  if (!bundledSchema) return null;
  const defs = bundledSchema.$defs;
  if (!defs || typeof defs !== "object") return null;
  const bucket = defs as Record<string, unknown>;
  const direct = bucket[ref];
  if (direct && typeof direct === "object") return direct as Record<string, unknown>;
  const hash = ref.match(/^#\/\$defs\/(.+)$/);
  if (hash) {
    const node = bucket[hash[1]];
    if (node && typeof node === "object") return node as Record<string, unknown>;
  }
  return null;
}
