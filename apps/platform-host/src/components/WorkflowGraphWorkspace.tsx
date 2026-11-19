"use client";

import { createPlatformBffClient } from "@goliath/client";
import { RecordDialog, RecordGrid, ReferencePicker, SchemaPropertyGrid } from "@goliath/platform-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createHostMetaCatalogResolver } from "@/lib/meta-catalog-resolver";
import {
  fetchRecordDocument,
  fetchRecordRows,
  runRecordEditorAction,
  saveRecordDocument,
} from "@/lib/record-editor-client";
import { linkedVersionId } from "@/lib/domain-program-structure";
import {
  editableGraphDocument,
  graphSchemaFor,
  NODE_TYPES,
  type GraphEditorMode,
} from "@/lib/workflow-graph-schemas";
import {
  addNode,
  connect,
  findNode,
  nodeBindings,
  nodeKeys,
  nodeParameterGridSchema,
  removeNodes,
  setNodeBindings,
  type ParameterBinding,
} from "@/lib/workflow-graph-edit";
import { WorkflowGraphCanvas } from "@/components/WorkflowGraphCanvas";

const ENTITY = "workflow_version";

const NEW_WORKFLOW_SCHEMA: Record<string, unknown> = {
  type: "object",
  properties: {
    name: { type: "string", description: "Workflow name (letters, digits, _ . : / -)" },
    description: { type: "string" },
    root_node_type: { type: "string", enum: ["SEQUENCE", "PARALLEL"], default: "SEQUENCE" },
  },
  required: ["name"],
};

type Templates = Record<string, Record<string, unknown>>;

function templatesOf(spec: Record<string, unknown>): Templates {
  const out: Templates = {};
  const nodes = Array.isArray(spec.nodes) ? (spec.nodes as Record<string, unknown>[]) : [];
  for (const n of nodes) {
    if (n && typeof n.node_key === "string" && n.input_template && typeof n.input_template === "object") {
      out[n.node_key] = n.input_template as Record<string, unknown>;
    }
  }
  return out;
}

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
  // Designer draft state: input templates by node key (edited ones are sent on save).
  const [templates, setTemplates] = useState<Templates>({});
  const [editedTemplates, setEditedTemplates] = useState<Set<string>>(new Set());
  const [bindingsDirty, setBindingsDirty] = useState(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [newType, setNewType] = useState<string>("ACTION");
  const [newAction, setNewAction] = useState("");
  const [connectTarget, setConnectTarget] = useState("");
  const [paramSchema, setParamSchema] = useState<Record<string, unknown> | null>(null);
  const [paramError, setParamError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

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
        const spec = (data.spec ?? {}) as Record<string, unknown>;
        setDoc(editableGraphDocument(mode, spec));
        setTemplates(templatesOf(spec));
        setEditedTemplates(new Set());
        setBindingsDirty(false);
        setSelectedNode(null);
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
        const payload: Record<string, unknown> = { ...edited };
        if (Array.isArray(payload.nodes)) {
          payload.nodes = (payload.nodes as Record<string, unknown>[]).map((n) => {
            const key = typeof n?.node_key === "string" ? n.node_key : "";
            return key && editedTemplates.has(key) ? { ...n, input_template: templates[key] ?? {} } : n;
          });
        }
        if (bindingsDirty && doc && !("input_bindings" in payload)) payload.input_bindings = doc.input_bindings ?? [];
        const newId = await saveRecordDocument(ENTITY, String(selected.workflow_version_id), payload);
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
        const spec = (data.spec ?? {}) as Record<string, unknown>;
        setDoc(editableGraphDocument(mode, spec));
        setTemplates(templatesOf(spec));
        setEditedTemplates(new Set());
        setBindingsDirty(false);
        setSession((n) => n + 1);
        setStatus(`Saved ${row.workflow_def_name} v${row.version} (inactive). Activate it to use it for new runs.`);
      } catch (e) {
        setStatus(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [mode, reload, selected, templates, editedTemplates, bindingsDirty, doc],
  );

  /** Canvas / toolbar edits replace the draft and refresh the grid below. */
  const applyDraft = useCallback((next: Record<string, unknown>) => {
    setDoc(next);
    setSession((n) => n + 1);
  }, []);

  const selectedNodeRow = useMemo(
    () => (doc && selectedNode ? findNode(doc, selectedNode) : undefined),
    [doc, selectedNode],
  );
  const selectedAction =
    selectedNodeRow && selectedNodeRow.node_type === "ACTION" && typeof selectedNodeRow.action_name === "string"
      ? selectedNodeRow.action_name
      : null;

  useEffect(() => {
    setParamSchema(null);
    setParamError(null);
    if (!selectedAction) return;
    let cancelled = false;
    void fetch(`/api/portal/workflows/action-parameters?action=${encodeURIComponent(selectedAction)}`, {
      credentials: "same-origin",
    })
      .then(async (res) => {
        const body = (await res.json()) as { schema?: Record<string, unknown>; error?: string };
        if (cancelled) return;
        if (!res.ok) setParamError(body.error ?? `HTTP ${res.status}`);
        else setParamSchema(body.schema ?? { type: "object", properties: {} });
      })
      .catch((e: unknown) => {
        if (!cancelled) setParamError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAction]);

  const applyParameters = useCallback(
    (edited: Record<string, unknown>) => {
      if (!doc || !selectedNode) return;
      const values = (edited.values ?? {}) as Record<string, unknown>;
      const clean = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== undefined && v !== ""));
      setTemplates((t) => ({ ...t, [selectedNode]: clean }));
      setEditedTemplates((set) => new Set(set).add(selectedNode));
      const bindings = Array.isArray(edited.bindings) ? (edited.bindings as ParameterBinding[]) : [];
      applyDraft(setNodeBindings(doc, selectedNode, bindings));
      setBindingsDirty(true);
      setStatus(`Parameters of ${selectedNode} updated in the draft. Save as new version to keep them.`);
    },
    [doc, selectedNode, applyDraft],
  );

  const createWorkflow = useCallback(
    async (edited: Record<string, unknown>) => {
      setCreateError(null);
      try {
        const id = await saveRecordDocument(ENTITY, null, edited);
        setCreating(false);
        const next = await reload();
        const row = next?.find((r) => String(r.workflow_version_id) === String(id));
        setStatus(`Created workflow ${String(edited.name ?? "")} (inactive v1.0)`);
        if (row) void open(row);
      } catch (e) {
        setCreateError(e instanceof Error ? e.message : String(e));
      }
    },
    [open, reload],
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
        noun="workflow"
        columns={GRAPH_COLUMNS}
        rows={gridRows}
        rowKey={(r) => String(r.workflow_version_id)}
        rowLabel={(r) => `${r.workflow_def_name} v${r.version}`}
        loading={loading}
        onRefresh={() => void reload()}
        onAdd={() => {
          setCreateError(null);
          setCreating(true);
        }}
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
            {!readOnly ? (
              <div className="g-graph-toolbar" role="toolbar" aria-label="workflow designer">
                <label>
                  Node type{" "}
                  <select value={newType} onChange={(e) => setNewType(e.target.value)} aria-label="New node type">
                    {NODE_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </label>
                {newType === "ACTION" ? (
                  <ReferencePicker fieldName="new_action" kind="action" value={newAction} onChange={setNewAction} />
                ) : null}
                <button
                  type="button"
                  className="g-host-button"
                  disabled={newType === "ACTION" && !newAction}
                  onClick={() => {
                    const res = addNode(doc, { node_type: newType, action_name: newAction || null }, selectedNode);
                    applyDraft(res.doc);
                    setSelectedNode(res.key);
                  }}
                >
                  {selectedNode ? `Add node under ${selectedNode}` : "Add node"}
                </button>
                {selectedNode ? (
                  <>
                    <label>
                      Connect {selectedNode} to{" "}
                      <select
                        value={connectTarget}
                        onChange={(e) => setConnectTarget(e.target.value)}
                        aria-label="Connect to node"
                      >
                        <option value="">—</option>
                        {nodeKeys(doc)
                          .filter((k) => k !== selectedNode)
                          .map((k) => (
                            <option key={k} value={k}>
                              {k}
                            </option>
                          ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="g-host-button"
                      disabled={!connectTarget}
                      onClick={() => {
                        applyDraft(connect(doc, selectedNode, connectTarget));
                        setConnectTarget("");
                      }}
                    >
                      Connect
                    </button>
                    {selectedNode !== doc.root_node_key ? (
                      <button
                        type="button"
                        className="g-host-button"
                        onClick={() => {
                          applyDraft(removeNodes(doc, [selectedNode]));
                          setSelectedNode(null);
                        }}
                      >
                        Remove {selectedNode}
                      </button>
                    ) : null}
                  </>
                ) : null}
              </div>
            ) : null}
            <WorkflowGraphCanvas
              spec={doc}
              onChange={readOnly ? undefined : applyDraft}
              selectedNodeKey={selectedNode}
              onSelectNode={setSelectedNode}
            />
            {!readOnly ? (
              <p className="g-record-editor__note">
                Drag from a node&apos;s lower edge to another node to connect them; select a node or edge and press
                Delete to remove it. Canvas edits refresh the property grid below.
              </p>
            ) : null}
            {selectedAction ? (
              <section className="g-graph-params" aria-label={`parameters of ${selectedNode}`}>
                <h4>
                  Parameters of {selectedNode} ({selectedAction})
                </h4>
                {paramError ? (
                  <p role="alert" className="g-record-editor__error">
                    {paramError}
                  </p>
                ) : paramSchema ? (
                  <SchemaPropertyGrid
                    key={`params:${selectedNode}:${session}`}
                    fields={[]}
                    flattenedSchema={nodeParameterGridSchema(paramSchema)}
                    catalogResolver={catalogResolver}
                    documentClassFqn="WorkflowNodeParameters"
                    initialDocument={{
                      values: templates[selectedNode ?? ""] ?? {},
                      bindings: nodeBindings(doc, selectedNode ?? ""),
                    }}
                    disabled={readOnly}
                    onSubmit={readOnly ? undefined : applyParameters}
                    submitLabel="Apply parameters"
                  />
                ) : (
                  <p role="status">Loading parameters…</p>
                )}
              </section>
            ) : null}
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
      <RecordDialog
        open={creating}
        title="New workflow"
        onClose={() => setCreating(false)}
        testId={`record-dialog-workflow_new`}
      >
        {createError ? (
          <p role="alert" className="g-record-editor__error">
            {createError}
          </p>
        ) : null}
        <p className="g-record-editor__note">
          Creates the definition with an inactive version 1.0 holding one root node. Add steps in the designer, save as
          a new version, then Activate.
        </p>
        <SchemaPropertyGrid
          key={`new:${creating}`}
          fields={[]}
          flattenedSchema={NEW_WORKFLOW_SCHEMA}
          catalogResolver={catalogResolver}
          documentClassFqn="WorkflowDefinition"
          initialDocument={{ root_node_type: "SEQUENCE" }}
          onSubmit={createWorkflow}
          submitLabel="Create workflow"
        />
      </RecordDialog>
    </div>
  );
}
