export type ViewVisibility = "scope" | "organization" | "private";

export type ColumnFormat = "text" | "number" | "date" | "currency";

export type ViewColumn = {
  field: string;
  label: string;
  format?: ColumnFormat;
};

export type FilterOperator =
  | "eq"
  | "neq"
  | "contains"
  | "starts_with"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "is_null";

export type ViewFilter = {
  field: string;
  operator: FilterOperator;
  value?: string | number | boolean;
};

export type ViewSort = {
  field: string;
  direction: "asc" | "desc";
};

export type AggregationFn = "count" | "sum" | "avg" | "min" | "max";

export type ViewAggregation = {
  field: string;
  fn: AggregationFn;
};

export type VisualizationType = "table" | "bar" | "line" | "pie" | "kpi";

export type ViewVisualization = {
  type: VisualizationType;
  categoryField?: string;
  valueField?: string;
  seriesField?: string;
};

export type ViewDefinition = {
  columns: ViewColumn[];
  filters: ViewFilter[];
  sort: ViewSort[];
  groupBy: string[];
  aggregations: ViewAggregation[];
  limit: number;
  visualization: ViewVisualization;
  visibility?: ViewVisibility;
};

export type DashboardFilter = ViewFilter;

export type DashboardLayout = {
  dashboardFilters: DashboardFilter[];
  viewMode?: boolean;
};

export const DEFAULT_VIEW_DEFINITION: ViewDefinition = {
  columns: [],
  filters: [],
  sort: [],
  groupBy: [],
  aggregations: [],
  limit: 50,
  visualization: { type: "table" },
  visibility: "scope",
};

export function parseViewDefinition(raw: Record<string, unknown> | undefined): ViewDefinition {
  if (!raw || typeof raw !== "object") {
    return { ...DEFAULT_VIEW_DEFINITION };
  }
  const vis = raw.visualization;
  const visualization: ViewVisualization =
    vis && typeof vis === "object" && vis !== null
      ? {
          type: normalizeVizType((vis as Record<string, unknown>).type),
          categoryField: stringOrUndefined((vis as Record<string, unknown>).categoryField),
          valueField: stringOrUndefined((vis as Record<string, unknown>).valueField),
          seriesField: stringOrUndefined((vis as Record<string, unknown>).seriesField),
        }
      : { type: "table" };
  return {
    columns: Array.isArray(raw.columns) ? (raw.columns as ViewColumn[]) : [],
    filters: Array.isArray(raw.filters) ? (raw.filters as ViewFilter[]) : [],
    sort: Array.isArray(raw.sort) ? (raw.sort as ViewSort[]) : [],
    groupBy: Array.isArray(raw.groupBy) ? (raw.groupBy as string[]) : [],
    aggregations: Array.isArray(raw.aggregations) ? (raw.aggregations as ViewAggregation[]) : [],
    limit: typeof raw.limit === "number" && raw.limit > 0 ? raw.limit : 50,
    visualization,
    visibility: normalizeVisibility(raw.visibility),
  };
}

function normalizeVizType(value: unknown): VisualizationType {
  if (
    value === "bar" ||
    value === "line" ||
    value === "pie" ||
    value === "kpi" ||
    value === "table"
  ) {
    return value;
  }
  return "table";
}

function normalizeVisibility(value: unknown): ViewVisibility {
  if (value === "organization" || value === "private") {
    return value;
  }
  return "scope";
}

function stringOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export function buildSemanticRunParams(definition: ViewDefinition): Record<string, unknown> {
  const params: Record<string, unknown> = { limit: definition.limit };
  const filterPredicates: Array<Record<string, string>> = [];
  let paramIdx = 0;
  for (const f of definition.filters) {
    if (f.operator === "is_null") {
      filterPredicates.push({ attribute: f.field, op: "is_null" });
      continue;
    }
    const paramKey = `f${paramIdx++}`;
    const semanticOp = mapFilterOp(f.operator);
    if (!semanticOp) continue;
    filterPredicates.push({ attribute: f.field, op: semanticOp, param: paramKey });
    params[paramKey] = f.value ?? "";
  }
  const out: Record<string, unknown> = { ...params };
  if (filterPredicates.length > 0) {
    out.filter_template = { all_of: filterPredicates };
  }
  if (definition.sort.length > 0) {
    out.order_by = definition.sort.map((s) => ({
      attribute: s.field,
      direction: s.direction,
    }));
  }
  return out;
}

function mapFilterOp(op: FilterOperator): string | null {
  switch (op) {
    case "eq":
      return "eq";
    case "neq":
      return "neq";
    case "contains":
      return "contains";
    case "starts_with":
      return "starts_with";
    case "gt":
      return "gt";
    case "gte":
      return "gte";
    case "lt":
      return "lt";
    case "lte":
      return "lte";
    case "is_null":
      return "is_null";
    default: {
      const _exhaustive: never = op;
      return _exhaustive;
    }
  }
}

function filterValueActive(filter: ViewFilter): boolean {
  if (filter.operator === "is_null") {
    return true;
  }
  const value = filter.value;
  if (value === undefined || value === null) {
    return false;
  }
  if (typeof value === "string" && value.length === 0) {
    return false;
  }
  return true;
}

function rowFieldValue(row: Record<string, unknown>, field: string): unknown {
  if (Object.hasOwn(row, field)) {
    return row[field];
  }
  const segments = field.split(".");
  let current: unknown = row;
  for (const segment of segments) {
    if (current == null || typeof current !== "object" || Array.isArray(current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

function rowMatchesFilter(row: Record<string, unknown>, filter: ViewFilter): boolean {
  const fieldValue = rowFieldValue(row, filter.field);
  const expected = filter.value;
  switch (filter.operator) {
    case "is_null":
      return fieldValue === null || fieldValue === undefined;
    case "eq":
      return String(fieldValue ?? "") === String(expected ?? "");
    case "neq":
      return String(fieldValue ?? "") !== String(expected ?? "");
    case "contains":
      return String(fieldValue ?? "")
        .toLowerCase()
        .includes(String(expected ?? "").toLowerCase());
    case "starts_with":
      return String(fieldValue ?? "")
        .toLowerCase()
        .startsWith(String(expected ?? "").toLowerCase());
    case "gt":
    case "gte":
    case "lt":
    case "lte": {
      const left = Number(fieldValue);
      const right = Number(expected);
      if (Number.isNaN(left) || Number.isNaN(right)) {
        return false;
      }
      if (filter.operator === "gt") return left > right;
      if (filter.operator === "gte") return left >= right;
      if (filter.operator === "lt") return left < right;
      return left <= right;
    }
    default: {
      const _exhaustive: never = filter.operator;
      return _exhaustive;
    }
  }
}

export function applyViewFilters(
  rows: Record<string, unknown>[],
  filters: ViewFilter[],
): Record<string, unknown>[] {
  const active = filters.filter(filterValueActive);
  if (active.length === 0) {
    return rows;
  }
  return rows.filter((row) => active.every((filter) => rowMatchesFilter(row, filter)));
}

export function previewColumns(
  definition: ViewDefinition,
  rowSample: Record<string, unknown> | undefined,
): { key: string; label: string }[] {
  if (definition.columns.length > 0) {
    return definition.columns.map((c) => ({ key: c.field, label: c.label || c.field }));
  }
  if (rowSample) {
    return Object.keys(rowSample).map((k) => ({ key: k, label: k.replace(/_/g, " ") }));
  }
  return [];
}

export function mergeVizOverride(
  base: ViewVisualization,
  override: Partial<ViewVisualization> | undefined,
): ViewVisualization {
  if (!override) return base;
  return {
    type: override.type ?? base.type,
    categoryField: override.categoryField ?? base.categoryField,
    valueField: override.valueField ?? base.valueField,
    seriesField: override.seriesField ?? base.seriesField,
  };
}
