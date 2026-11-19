"use client";

import type { ReactNode } from "react";
import { useEffect, useId, useMemo, useState } from "react";

/**
 * Generic record grid: sortable, filterable rows with a toolbar (Refresh, Add) and per-row
 * View / Edit / extra actions. It knows nothing about the record type; callers pass column
 * metadata (from record-editor definitions, Meta class fields or query metadata) and callbacks.
 * View and Edit are expected to open the record in a {@link RecordDialog}, not inline forms.
 */
export type RecordGridColumn = { key: string; label: string };

export type RecordGridRowAction<Row> = {
  id: string;
  label: string;
  visible?: (row: Row) => boolean;
  onRun: (row: Row) => void;
};

export type RecordGridProps<Row extends Record<string, unknown>> = {
  title: string;
  /** Singular noun for button labels ("cluster", "class"). */
  noun?: string;
  columns: RecordGridColumn[];
  rows: Row[];
  rowKey: (row: Row) => string;
  rowLabel?: (row: Row) => string;
  loading?: boolean;
  onRefresh?: () => void;
  onAdd?: () => void;
  onView?: (row: Row) => void;
  onEdit?: (row: Row) => void;
  canEdit?: (row: Row) => boolean;
  rowActions?: RecordGridRowAction<Row>[];
  selectedKey?: string | null;
  /** Extra toolbar content (filters specific to the page, links). */
  toolbarSlot?: ReactNode;
  testId?: string;
  /** Optional data-testid per row. */
  rowTestId?: (row: Row) => string;
  emptyText?: string;
};

export function formatRecordCell(value: unknown): string {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.map((v) => formatRecordCell(v)).join(", ");
  if (typeof value === "object") {
    const n = Object.keys(value as object).length;
    return n === 0 ? "—" : `${n} field(s)`;
  }
  return String(value);
}

type SortState = { key: string; dir: "asc" | "desc" } | null;

function compareCells(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  const na = typeof a === "number" ? a : typeof a === "string" && a.trim() !== "" ? Number(a) : NaN;
  const nb = typeof b === "number" ? b : typeof b === "string" && b.trim() !== "" ? Number(b) : NaN;
  if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return formatRecordCell(a).localeCompare(formatRecordCell(b), undefined, { numeric: true, sensitivity: "base" });
}

/** Rows whose visible cells contain every whitespace-separated term (case-insensitive). */
export function filterRecordRows<Row extends Record<string, unknown>>(
  rows: Row[],
  columns: RecordGridColumn[],
  filter: string,
): Row[] {
  const terms = filter.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return rows;
  return rows.filter((row) => {
    const text = columns.map((c) => formatRecordCell(row[c.key])).join(" ").toLowerCase();
    return terms.every((t) => text.includes(t));
  });
}

export function sortRecordRows<Row extends Record<string, unknown>>(rows: Row[], sort: SortState): Row[] {
  if (!sort) return rows;
  const sorted = [...rows].sort((a, b) => compareCells(a[sort.key], b[sort.key]));
  return sort.dir === "desc" ? sorted.reverse() : sorted;
}

export function RecordGrid<Row extends Record<string, unknown>>({
  title,
  noun = "record",
  columns,
  rows,
  rowKey,
  rowLabel,
  loading = false,
  onRefresh,
  onAdd,
  onView,
  onEdit,
  canEdit,
  rowActions = [],
  selectedKey,
  toolbarSlot,
  testId,
  rowTestId,
  emptyText = "No records",
}: RecordGridProps<Row>) {
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortState>(null);
  const filterId = useId();
  const label = rowLabel ?? rowKey;
  const visible = useMemo(
    () => sortRecordRows(filterRecordRows(rows, columns, filter), sort),
    [rows, columns, filter, sort],
  );
  const hasRowButtons = Boolean(onView || onEdit || rowActions.length);

  const toggleSort = (key: string) =>
    setSort((s) => (s?.key !== key ? { key, dir: "asc" } : s.dir === "asc" ? { key, dir: "desc" } : null));

  return (
    <section className="g-record-grid" data-testid={testId} aria-label={title}>
      <header className="g-record-grid__toolbar">
        <h3 className="g-record-grid__title">{title}</h3>
        <label htmlFor={filterId} className="g-sr-only">
          Filter {title}
        </label>
        <input
          id={filterId}
          type="search"
          className="g-record-grid__filter"
          placeholder="Filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <span className="g-record-grid__count" role="status">
          {filter ? `${visible.length} of ${rows.length}` : `${rows.length}`} {rows.length === 1 ? noun : `${noun}s`}
        </span>
        {toolbarSlot}
        {onRefresh ? (
          <button type="button" className="g-host-button" onClick={onRefresh} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        ) : null}
        {onAdd ? (
          <button
            type="button"
            className="g-host-button g-host-button--primary"
            onClick={onAdd}
            data-testid={testId ? `${testId}-add` : undefined}
          >
            Add {noun}
          </button>
        ) : null}
      </header>
      <div className="g-portal-table-wrap">
        <table className="g-host-table g-record-grid__table">
          <thead>
            <tr>
              {columns.map((c) => {
                const dir = sort?.key === c.key ? sort.dir : null;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none"}
                  >
                    <button type="button" className="g-record-grid__sort" onClick={() => toggleSort(c.key)}>
                      {c.label}
                      <span aria-hidden="true">{dir === "asc" ? " ▲" : dir === "desc" ? " ▼" : ""}</span>
                    </button>
                  </th>
                );
              })}
              {hasRowButtons ? (
                <th scope="col">
                  <span className="g-sr-only">Actions</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={columns.length + (hasRowButtons ? 1 : 0)}>
                  {loading ? "Loading…" : filter ? "No matching records" : emptyText}
                </td>
              </tr>
            ) : (
              visible.map((row) => {
                const key = rowKey(row);
                const active = selectedKey != null && key === selectedKey;
                return (
                  <tr
                    key={key}
                    aria-selected={active}
                    className={active ? "is-selected" : undefined}
                    data-testid={rowTestId?.(row)}
                  >
                    {columns.map((c) => (
                      <td key={c.key}>{formatRecordCell(row[c.key])}</td>
                    ))}
                    {hasRowButtons ? (
                      <td className="g-record-grid__row-actions">
                        {onView ? (
                          <button type="button" onClick={() => onView(row)} aria-label={`View ${label(row)}`}>
                            View
                          </button>
                        ) : null}
                        {onEdit && (canEdit == null || canEdit(row)) ? (
                          <button type="button" onClick={() => onEdit(row)} aria-label={`Edit ${label(row)}`}>
                            Edit
                          </button>
                        ) : null}
                        {rowActions
                          .filter((a) => a.visible == null || a.visible(row))
                          .map((a) => (
                            <button
                              key={a.id}
                              type="button"
                              onClick={() => a.onRun(row)}
                              aria-label={`${a.label} ${label(row)}`}
                            >
                              {a.label}
                            </button>
                          ))}
                      </td>
                    ) : null}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * Side drawer for viewing or editing one record. Escape and the backdrop close it, unless a
 * nested property inspector is open on top (that one handles Escape first).
 */
export function RecordDialog({
  open,
  title,
  onClose,
  children,
  testId,
  size = "normal",
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  testId?: string;
  /** "wide" for designers (dashboard canvas, view editor). */
  size?: "normal" | "wide";
}) {
  const titleId = useId();
  useEffect(() => {
    if (!open || typeof window === "undefined") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (typeof document !== "undefined" && document.querySelector(".g-property-inspector-modal")) return;
      e.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="g-record-dialog-backdrop">
      <button type="button" className="g-schema-dialog-backdrop__hit" aria-label="Close" onClick={onClose} />
      <aside
        className={size === "wide" ? "g-record-dialog g-record-dialog--wide" : "g-record-dialog"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid={testId}
      >
        <header className="g-record-dialog__header">
          <h3 id={titleId}>{title}</h3>
          <button type="button" className="g-host-button" onClick={onClose} aria-label={`Close ${title}`}>
            Close
          </button>
        </header>
        <div className="g-record-dialog__body">{children}</div>
      </aside>
    </div>
  );
}
