"use client";

import { RecordDialog, RecordGrid, SchemaPropertyGrid } from "@goliath/platform-ui";
import { useMemo, useState } from "react";

export type QueryRecordGridProps = {
  title: string;
  noun?: string;
  columns: { key: string; label: string }[];
  rows: Record<string, unknown>[];
  /** Column holding a stable row key; defaults to the row position. */
  keyColumn?: string;
};

/** Read-only JSON Schema for a query row: one property per column, typed from the values. */
export function rowViewSchema(
  columns: { key: string; label: string }[],
  rows: Record<string, unknown>[],
): Record<string, unknown> {
  const properties: Record<string, unknown> = {};
  for (const c of columns) {
    const sample = rows.find((r) => r[c.key] != null)?.[c.key];
    const type =
      typeof sample === "number"
        ? Number.isInteger(sample)
          ? "integer"
          : "number"
        : typeof sample === "boolean"
          ? "boolean"
          : Array.isArray(sample)
            ? "array"
            : sample != null && typeof sample === "object"
              ? "object"
              : "string";
    properties[c.key] =
      type === "array" ? { type, title: c.label, items: { type: "string" } } : { type, title: c.label };
  }
  return { type: "object", properties };
}

function viewDocument(columns: { key: string }[], row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const c of columns) {
    const v = row[c.key];
    if (v == null) continue;
    out[c.key] = Array.isArray(v) ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))) : v;
  }
  return out;
}

/**
 * Read-only lists (platform queries, semantic requests): sortable, filterable grid with a
 * per-row View drawer showing the row in the typed property grid.
 */
export function QueryRecordGrid({ title, noun = "row", columns, rows, keyColumn }: QueryRecordGridProps) {
  const keyed = useMemo(
    () => rows.map((r, i) => ({ ...r, __rowKey: keyColumn && r[keyColumn] != null ? String(r[keyColumn]) : String(i) })),
    [rows, keyColumn],
  );
  const schema = useMemo(() => rowViewSchema(columns, rows), [columns, rows]);
  const [viewing, setViewing] = useState<Record<string, unknown> | null>(null);
  const label = (r: Record<string, unknown>) => {
    const first = columns[0]?.key;
    return first && r[first] != null ? String(r[first]) : `${noun} ${String(r.__rowKey)}`;
  };
  return (
    <>
      <RecordGrid
        title={title}
        noun={noun}
        columns={columns}
        rows={keyed}
        rowKey={(r) => String(r.__rowKey)}
        rowLabel={label}
        onView={(r) => setViewing(r)}
        selectedKey={viewing ? String(viewing.__rowKey) : null}
      />
      <RecordDialog open={viewing != null} title={viewing ? label(viewing) : ""} onClose={() => setViewing(null)}>
        {viewing ? (
          <SchemaPropertyGrid
            key={String(viewing.__rowKey)}
            fields={[]}
            flattenedSchema={schema}
            documentClassFqn={title}
            initialDocument={viewDocument(columns, viewing)}
            disabled
          />
        ) : null}
      </RecordDialog>
    </>
  );
}
