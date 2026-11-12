"use client";

import { createPlatformBffClient } from "@goliath/client";
import { SchemaPropertyGrid } from "@goliath/platform-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createHostMetaCatalogResolver } from "@/lib/meta-catalog-resolver";
import {
  editableDocument,
  mergeIdentityForSave,
  RECORD_EDITORS,
  type RecordEditorDefinition,
} from "@/lib/record-editor-schemas";
import {
  fetchRecordDocument,
  fetchRecordRows,
  runRecordEditorAction,
  saveRecordDocument,
} from "@/lib/record-editor-client";

function cell(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

export type RecordEditorWorkspaceProps = {
  entity: keyof typeof RECORD_EDITORS | string;
};

/**
 * Generic list + typed property-grid inspector for one Workflows record entity.
 * Selecting a row loads its document; saves go through the session-gated portal writers.
 */
export function RecordEditorWorkspace({ entity }: RecordEditorWorkspaceProps) {
  const def: RecordEditorDefinition | undefined = RECORD_EDITORS[entity];
  const client = useMemo(() => createPlatformBffClient(), []);
  const catalogResolver = useMemo(() => createHostMetaCatalogResolver(client), [client]);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [document, setDocument] = useState<Record<string, unknown> | null>(null);
  const [original, setOriginal] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState(0);
  const selectSeq = useRef(0);

  const reload = useCallback(async () => {
    if (!def) return;
    setLoading(true);
    try {
      setRows(await fetchRecordRows(def.entity));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [def]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const select = useCallback(
    async (row: Record<string, unknown>) => {
      if (!def) return;
      const key = def.rowKey(row);
      const seq = ++selectSeq.current;
      setCreating(false);
      setSelectedKey(key);
      setDocument(null);
      setError(null);
      setStatus(null);
      try {
        const doc = await fetchRecordDocument(def.entity, key);
        if (seq !== selectSeq.current) return;
        setOriginal({ ...row, ...doc });
        setDocument(editableDocument(def.editSchema, doc));
        setSession((n) => n + 1);
      } catch (e) {
        if (seq === selectSeq.current) setError(e instanceof Error ? e.message : String(e));
      }
    },
    [def],
  );

  const startNew = useCallback(() => {
    selectSeq.current++;
    setSelectedKey(null);
    setOriginal(null);
    setCreating(true);
    setDocument({});
    setError(null);
    setStatus(null);
    setSession((n) => n + 1);
  }, []);

  const save = useCallback(
    async (edited: Record<string, unknown>) => {
      if (!def) return;
      setError(null);
      setStatus("Saving…");
      try {
        const payload = mergeIdentityForSave(def.entity, selectedKey, original, edited);
        const key = await saveRecordDocument(def.entity, creating ? null : selectedKey, payload);
        setStatus(creating ? `Created ${def.noun} ${key}` : `Saved ${def.noun} ${key}`);
        await reload();
        const doc = await fetchRecordDocument(def.entity, key);
        setCreating(false);
        setSelectedKey(key);
        setOriginal(doc);
        setDocument(editableDocument(def.editSchema, doc));
        setSession((n) => n + 1);
      } catch (e) {
        setStatus(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [creating, def, original, reload, selectedKey],
  );

  const runAction = useCallback(
    async (action: string, row: Record<string, unknown>, label: string) => {
      if (!def) return;
      setError(null);
      try {
        await runRecordEditorAction(def.entity, action, def.rowKey(row));
        setStatus(`${label}: ${def.rowLabel(row)}`);
        await reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [def, reload],
  );

  if (!def) {
    return <p role="alert">Unknown record editor: {entity}</p>;
  }

  const schema = creating ? def.createSchema : def.editSchema;
  const selectedRow = rows.find((r) => def.rowKey(r) === selectedKey);

  return (
    <section className="g-record-editor" data-testid={`record-editor-${def.entity}`}>
      <header className="g-record-editor__toolbar">
        <h3>{def.title}</h3>
        <button type="button" onClick={() => void reload()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
        {def.canCreate ? (
          <button type="button" onClick={startNew} data-testid={`record-editor-new-${def.entity}`}>
            New {def.noun}
          </button>
        ) : null}
      </header>
      {error ? (
        <p role="alert" className="g-record-editor__error">
          {error}
        </p>
      ) : null}
      {status ? <p role="status">{status}</p> : null}
      <div className="g-record-editor__body">
        <table className="g-record-editor__table">
          <thead>
            <tr>
              {def.columns.map((c) => (
                <th key={c.key} scope="col">
                  {c.label}
                </th>
              ))}
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={def.columns.length + 1}>{loading ? "Loading…" : "No records"}</td>
              </tr>
            ) : (
              rows.map((row) => {
                const key = def.rowKey(row);
                const active = key === selectedKey && !creating;
                return (
                  <tr key={key} aria-selected={active} className={active ? "is-selected" : undefined}>
                    {def.columns.map((c) => (
                      <td key={c.key}>{cell(row[c.key])}</td>
                    ))}
                    <td className="g-record-editor__row-actions">
                      <button type="button" onClick={() => void select(row)} aria-label={`Edit ${def.rowLabel(row)}`}>
                        Edit
                      </button>
                      {(def.rowActions ?? [])
                        .filter((a) => a.visible(row))
                        .map((a) => (
                          <button
                            key={a.action}
                            type="button"
                            onClick={() => void runAction(a.action, row, a.label)}
                            aria-label={`${a.label} ${def.rowLabel(row)}`}
                          >
                            {a.label}
                          </button>
                        ))}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
        {document ? (
          <div className="g-record-editor__inspector" aria-label={`${def.noun} inspector`}>
            <h4>
              {creating ? `New ${def.noun}` : selectedRow ? def.rowLabel(selectedRow) : (selectedKey ?? "")}
            </h4>
            <SchemaPropertyGrid
              key={`${def.entity}:${selectedKey ?? "new"}:${session}`}
              fields={[]}
              flattenedSchema={schema}
              catalogResolver={catalogResolver}
              documentClassFqn={def.title}
              initialDocument={document}
              onSubmit={save}
              submitLabel={creating ? `Create ${def.noun}` : "Save changes"}
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}
