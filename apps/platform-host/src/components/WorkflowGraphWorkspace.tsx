"use client";

import { createPlatformBffClient } from "@goliath/client";
import { RecordDialog, RecordGrid, SchemaPropertyGrid } from "@goliath/platform-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createHostMetaCatalogResolver } from "@/lib/meta-catalog-resolver";
import {
  fetchRecordDocument,
  fetchRecordRows,
  runRecordEditorAction,
  saveRecordDocument,
} from "@/lib/record-editor-client";
import { linkedVersionId } from "@/lib/domain-program-structure";
import { editableGraphDocument, graphSchemaFor, type GraphEditorMode } from "@/lib/workflow-graph-schemas";
import { WorkflowGraphCanvas } from "@/components/WorkflowGraphCanvas";

const ENTITY = "workflow_version";

type VersionRow = {
  workflow_version_id: number;
  workflow_def_name: string;
  version: string;
  is_active: boolean;
  node_count: number;
  run_count: number;
};

const GRAPH_COLUMNS = [
  { key: "workflow_def_name", label: "Workflow" },
  { key: "version", label: "Version" },
  { key: "active_label", label: "Active" },
  { key: "node_count", label: "Nodes" },
  { key: "run_count", label: "Runs" },
];

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
  const [readOnly, setReadOnly] = useState(false);
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
      const next = (await fetchRecordRows(ENTITY)).map(asVersionRow);
      setRows(next);
      return next;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const open = useCallback(
    async (row: VersionRow, view = false) => {
      const s = ++seq.current;
      setReadOnly(view);
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

  // Deep link (?version=<workflow_version_id>), e.g. "Open graph" from a domain program.
  const deepLinked = useRef(false);
  useEffect(() => {
    if (deepLinked.current || rows.length === 0 || typeof window === "undefined") return;
    deepLinked.current = true;
    const wanted = linkedVersionId(window.location.search);
    if (wanted == null) return;
    const row = rows.find((r) => r.workflow_version_id === wanted);
    if (row) void open(row);
    else setError(`Workflow version ${wanted} is not in this list.`);
  }, [open, rows]);

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
        const nextRows = await reload();
        setSelected((cur) => {
          if (!cur || !nextRows) return cur;
          return nextRows.find((r) => r.workflow_version_id === cur.workflow_version_id) ?? cur;
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [reload],
  );

  const close = useCallback(() => {
    seq.current++;
    setSelected(null);
    setDoc(null);
  }, []);

  const gridRows = useMemo(
    () => rows.map((r) => ({ ...r, active_label: r.is_active ? "active" : "" })),
    [rows],
  );

  return (
    <div className="g-record-editor" data-testid={`workflow-graph-${mode}`}>
      {error && !selected ? (
        <p role="alert" className="g-record-editor__error">
          {error}
        </p>
      ) : null}
      {status && !selected ? <p role="status">{status}</p> : null}
      <RecordGrid
        title={mode === "steps" ? "Steps (node graph)" : "Definitions (version graph)"}
        noun="version"
        columns={GRAPH_COLUMNS}
        rows={gridRows}
        rowKey={(r) => String(r.workflow_version_id)}
        rowLabel={(r) => `${r.workflow_def_name} v${r.version}`}
        loading={loading}
        onRefresh={() => void reload()}
        onView={(r) => void open(r, true)}
        onEdit={(r) => void open(r)}
        selectedKey={selected ? String(selected.workflow_version_id) : null}
        emptyText="No workflow versions"
        testId={`record-grid-workflow_${mode}`}
        rowActions={[
          { id: "activate", label: "Activate", visible: (r) => !r.is_active, onRun: (r) => void activate(r) },
        ]}
      />
      <RecordDialog
        open={selected != null}
        size="wide"
        title={
          selected
            ? `${selected.workflow_def_name} v${selected.version} ${selected.is_active ? "(active)" : "(inactive)"}`
            : ""
        }
        onClose={close}
        testId={`record-dialog-workflow_${mode}`}
      >
        {error ? (
          <p role="alert" className="g-record-editor__error">
            {error}
          </p>
        ) : null}
        {status ? <p role="status">{status}</p> : null}
        {doc && selected ? (
          <div aria-label="workflow version inspector">
            {!readOnly ? (
              <p className="g-record-editor__note">
                Saving creates a new inactive version of this workflow; the version shown here is not changed. Node
                input templates are carried over by node key. Event subscriptions keep pointing at their version.
              </p>
            ) : null}
            <WorkflowGraphCanvas spec={doc} />
            <SchemaPropertyGrid
              key={`graph:${selected.workflow_version_id}:${readOnly}:${session}`}
              fields={[]}
              flattenedSchema={graphSchemaFor(mode)}
              catalogResolver={catalogResolver}
              documentClassFqn="WorkflowVersion"
              initialDocument={doc}
              disabled={readOnly}
              onSubmit={readOnly ? undefined : save}
              submitLabel="Save as new version"
            />
            {readOnly ? (
              <button type="button" className="g-host-button" onClick={() => void open(selected)}>
                Edit
              </button>
            ) : null}
          </div>
        ) : error ? null : (
          <p role="status">Loading…</p>
        )}
      </RecordDialog>
    </div>
  );
}
