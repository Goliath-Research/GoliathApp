"use client";

import { createPlatformBffClient } from "@goliath/client";
import { SchemaPropertyGrid } from "@goliath/platform-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createHostMetaCatalogResolver } from "@/lib/meta-catalog-resolver";
import {
  fetchRecordDocument,
  fetchRecordRows,
  runRecordEditorAction,
  saveRecordDocument,
} from "@/lib/record-editor-client";
import { editableGraphDocument, graphSchemaFor, type GraphEditorMode } from "@/lib/workflow-graph-schemas";

const ENTITY = "workflow_version";

type VersionRow = {
  workflow_version_id: number;
  workflow_def_name: string;
  version: string;
  is_active: boolean;
  node_count: number;
  run_count: number;
};

function asVersionRow(r: Record<string, unknown>): VersionRow {
  return {
    workflow_version_id: Number(r.workflow_version_id),
    workflow_def_name: String(r.workflow_def_name ?? ""),
    version: String(r.version ?? ""),
    is_active: Boolean(r.is_active),
    node_count: Number(r.node_count ?? 0),
    run_count: Number(r.run_count ?? 0),
  };
}

/**
 * Workflow definitions / steps editor. Saving never edits a version in place: it creates a
 * new inactive version of the same definition; activation is an explicit separate action.
 */
export function WorkflowGraphWorkspace({ mode }: { mode: GraphEditorMode }) {
  const client = useMemo(() => createPlatformBffClient(), []);
  const catalogResolver = useMemo(() => createHostMetaCatalogResolver(client), [client]);
  const [rows, setRows] = useState<VersionRow[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<VersionRow | null>(null);
  const [doc, setDoc] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState(0);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setRows((await fetchRecordRows(ENTITY)).map(asVersionRow));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const open = useCallback(
    async (row: VersionRow) => {
      const s = ++seq.current;
      setSelected(row);
      setDoc(null);
      setError(null);
      setStatus(null);
      try {
        const data = await fetchRecordDocument(ENTITY, String(row.workflow_version_id));
        if (s !== seq.current) return;
        setDoc(editableGraphDocument(mode, (data.spec ?? {}) as Record<string, unknown>));
        setSession((n) => n + 1);
      } catch (e) {
        if (s === seq.current) setError(e instanceof Error ? e.message : String(e));
      }
    },
    [mode],
  );

  const save = useCallback(
    async (edited: Record<string, unknown>) => {
      if (!selected) return;
      setError(null);
      setStatus("Saving new version…");
      try {
        const newId = await saveRecordDocument(ENTITY, String(selected.workflow_version_id), edited);
        await reload();
        const data = await fetchRecordDocument(ENTITY, newId);
        const row: VersionRow = {
          workflow_version_id: Number(newId),
          workflow_def_name: String(data.workflow_def_name ?? selected.workflow_def_name),
          version: `${data.version_major}.${data.version_minor}`,
          is_active: Boolean(data.is_active),
          node_count: Array.isArray((data.spec as Record<string, unknown>)?.nodes)
            ? ((data.spec as Record<string, unknown>).nodes as unknown[]).length
            : 0,
          run_count: 0,
        };
        setSelected(row);
        setDoc(editableGraphDocument(mode, (data.spec ?? {}) as Record<string, unknown>));
        setSession((n) => n + 1);
        setStatus(`Saved ${row.workflow_def_name} v${row.version} (inactive). Activate it to use it for new runs.`);
      } catch (e) {
        setStatus(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [mode, reload, selected],
  );

  const activate = useCallback(
    async (row: VersionRow) => {
      setError(null);
      try {
        await runRecordEditorAction(ENTITY, "activate", String(row.workflow_version_id));
        setStatus(`Activated ${row.workflow_def_name} v${row.version}`);
        await reload();
        setSelected((cur) => (cur && cur.workflow_version_id === row.workflow_version_id ? { ...cur, is_active: true } : cur));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [reload],
  );

  const needle = filter.trim().toLowerCase();
  const visible = needle ? rows.filter((r) => r.workflow_def_name.toLowerCase().includes(needle)) : rows;

  return (
    <section className="g-record-editor" data-testid={`workflow-graph-${mode}`}>
      <header className="g-record-editor__toolbar">
        <h3>{mode === "steps" ? "Steps (node graph)" : "Definitions (version graph)"}</h3>
        <label>
          <span className="sr-only">Filter workflows</span>
          <input
            type="search"
            placeholder="Filter by workflow"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </label>
        <button type="button" onClick={() => void reload()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
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
              <th scope="col">Workflow</th>
              <th scope="col">Version</th>
              <th scope="col">Active</th>
              <th scope="col">Nodes</th>
              <th scope="col">Runs</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={6}>{loading ? "Loading…" : "No workflow versions"}</td>
              </tr>
            ) : (
              visible.map((r) => (
                <tr
                  key={r.workflow_version_id}
                  aria-selected={selected?.workflow_version_id === r.workflow_version_id}
                  className={selected?.workflow_version_id === r.workflow_version_id ? "is-selected" : undefined}
                >
                  <td>{r.workflow_def_name}</td>
                  <td>{r.version}</td>
                  <td>{r.is_active ? "active" : "—"}</td>
                  <td>{r.node_count}</td>
                  <td>{r.run_count}</td>
                  <td className="g-record-editor__row-actions">
                    <button
                      type="button"
                      onClick={() => void open(r)}
                      aria-label={`Edit ${r.workflow_def_name} v${r.version}`}
                    >
                      Edit
                    </button>
                    {!r.is_active ? (
                      <button
                        type="button"
                        onClick={() => void activate(r)}
                        aria-label={`Activate ${r.workflow_def_name} v${r.version}`}
                      >
                        Activate
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        {doc && selected ? (
          <div className="g-record-editor__inspector" aria-label="workflow version inspector">
            <h4>
              {selected.workflow_def_name} v{selected.version} {selected.is_active ? "(active)" : "(inactive)"}
            </h4>
            <p className="g-record-editor__note">
              Saving creates a new inactive version of this workflow; the version shown here is not changed. Node
              input templates are carried over by node key. Event subscriptions keep pointing at their version.
            </p>
            <SchemaPropertyGrid
              key={`graph:${selected.workflow_version_id}:${session}`}
              fields={[]}
              flattenedSchema={graphSchemaFor(mode)}
              catalogResolver={catalogResolver}
              documentClassFqn="WorkflowVersion"
              initialDocument={doc}
              onSubmit={save}
              submitLabel="Save as new version"
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}
