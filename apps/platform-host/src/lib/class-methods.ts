/** Pure helpers for the method-centric Actions editor. */

export type ClassMethodRow = {
  class_name: string;
  method_id: number;
  method_name: string;
  declared_on_class: string;
  inherited: boolean;
  inheritance_depth: number;
  is_override: boolean;
  is_abstract: boolean;
  is_final: boolean;
  impl_kind: string | null;
  impl_ref: string | null;
  description: string | null;
  param_count: number;
};

export type ClassMethodGroup = { className: string; methods: ClassMethodRow[] };

/** Group effective methods by owning class, classes and methods sorted by name. */
export function groupMethodsByClass(rows: ClassMethodRow[], filter = ""): ClassMethodGroup[] {
  const needle = filter.trim().toLowerCase();
  const byClass = new Map<string, ClassMethodRow[]>();
  for (const row of rows) {
    if (
      needle &&
      !row.class_name.toLowerCase().includes(needle) &&
      !row.method_name.toLowerCase().includes(needle) &&
      !(row.impl_ref ?? "").toLowerCase().includes(needle)
    ) {
      continue;
    }
    const list = byClass.get(row.class_name) ?? [];
    list.push(row);
    byClass.set(row.class_name, list);
  }
  return [...byClass.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([className, methods]) => ({
      className,
      methods: [...methods].sort((a, b) => a.method_name.localeCompare(b.method_name)),
    }));
}

/** Badge text describing where a method comes from. */
export function methodOrigin(row: ClassMethodRow): string {
  if (row.inherited) return `inherited from ${row.declared_on_class}`;
  if (row.is_override) return "override";
  return "declared";
}

/** Draft document for overriding an inherited method on the selected class. */
export function overrideDraft(
  row: ClassMethodRow,
  inheritedDocument: Record<string, unknown>,
): Record<string, unknown> {
  const draft: Record<string, unknown> = {
    class_name: row.class_name,
    method_name: row.method_name,
  };
  for (const key of ["description", "impl_kind", "action_name", "impl_ref", "return_type_id", "parameters"]) {
    const value = inheritedDocument[key];
    if (value !== undefined && value !== null) draft[key] = value;
  }
  return draft;
}

export function isClassMethodRow(value: unknown): value is ClassMethodRow {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.class_name === "string" && typeof v.method_name === "string" && v.method_id != null;
}
