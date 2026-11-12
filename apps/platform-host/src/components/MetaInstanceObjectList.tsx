"use client";

import type { MetaObjectListRow } from "@goliath/client";

export type MetaInstanceObjectListProps = {
  rows: MetaObjectListRow[];
  selectedObjId: number | null;
  includeSubclasses: boolean;
  loading?: boolean;
  onToggleSubclasses: (next: boolean) => void;
  onSelect: (objId: number) => void;
  onNew: () => void;
};

export function MetaInstanceObjectList({
  rows,
  selectedObjId,
  includeSubclasses,
  loading = false,
  onToggleSubclasses,
  onSelect,
  onNew,
}: MetaInstanceObjectListProps) {
  return (
    <section className="g-meta-instance-list" data-testid="meta-instance-list">
      <header className="g-meta-instance-list__header">
        <h3>Instances</h3>
        <label className="g-meta-instance-list__toggle">
          <input
            type="checkbox"
            checked={includeSubclasses}
            onChange={(e) => onToggleSubclasses(e.target.checked)}
          />
          Include subclasses
        </label>
        <button type="button" className="g-host-button" data-testid="meta-instance-new" onClick={onNew}>
          New
        </button>
      </header>
      {loading ? <p role="status">Loading instances…</p> : null}
      <table className="g-host-table">
        <thead>
          <tr>
            <th scope="col">ID</th>
            <th scope="col">Label</th>
            <th scope="col">Class</th>
            <th scope="col">Updated</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4}>No instances in this scope yet.</td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr
                key={row.objId}
                data-testid={`meta-instance-row-${row.objId}`}
                className={selectedObjId === row.objId ? "g-host-table__row--selected" : undefined}
                onClick={() => onSelect(row.objId)}
              >
                <td>{row.objId}</td>
                <td>{row.displayLabel}</td>
                <td>{row.className}</td>
                <td>{row.updatedAtUtc ?? "—"}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}
