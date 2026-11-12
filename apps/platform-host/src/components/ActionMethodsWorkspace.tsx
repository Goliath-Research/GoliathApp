"use client";

import { createPlatformBffClient } from "@goliath/client";
import { SchemaPropertyGrid } from "@goliath/platform-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  groupMethodsByClass,
  isClassMethodRow,
  methodOrigin,
  overrideDraft,
  type ClassMethodRow,
} from "@/lib/class-methods";
import { createHostMetaCatalogResolver } from "@/lib/meta-catalog-resolver";
import { fetchRecordDocument, fetchRecordRows, runRecordEditorAction, saveRecordDocument } from "@/lib/record-editor-client";
import { CLASS_METHOD_CREATE_SCHEMA, CLASS_METHOD_EDIT_SCHEMA, editableDocument } from "@/lib/record-editor-schemas";

const ENTITY = "class_method";

type Mode =
  | { kind: "none" }
  | { kind: "edit"; row: ClassMethodRow; methodId: number }
  | { kind: "create"; title: string };

/**
 * Method-centric Actions editor: actions are Meta class methods. Lists effective methods
 * per class (inherited and overriding rows visible); editing saves the Meta method and its
 * typed parameters, and the server synchronises the bound wf.workflow_action catalog row.
 */
export function ActionMethodsWorkspace() {
  const client = useMemo(() => createPlatformBffClient(), []);
  const catalogResolver = useMemo(() => createHostMetaCatalogResolver(client), [client]);
  const [rows, setRows] = useState<ClassMethodRow[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<Mode>({ kind: "none" });
  const [methodDoc, setMethodDoc] = useState<Record<string, unknown> | null>(null);
  const [fullDoc, setFullDoc] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState(0);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchRecordRows(ENTITY);
      setRows(data.filter(isClassMethodRow));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const groups = useMemo(() => groupMethodsByClass(rows, filter), [rows, filter]);

  const load = useCallback(async (row: ClassMethodRow) => {
    const s = ++seq.current;
    setError(null);
    setStatus(null);
    setMethodDoc(null);
    setFullDoc(null);
    try {
      const doc = await fetchRecordDocument(ENTITY, String(row.method_id));
      if (s !== seq.current) return;
      setFullDoc(doc);
      return doc;
    } catch (e) {
      if (s === seq.current) setError(e instanceof Error ? e.message : String(e));
      return undefined;
    }
  }, []);

  const edit = useCallback(
    async (row: ClassMethodRow) => {
      const doc = await load(row);
      if (!doc) return;
      setMode({ kind: "edit", row, methodId: row.method_id });
      setMethodDoc(editableDocument(CLASS_METHOD_EDIT_SCHEMA, doc));
      setSession((n) => n + 1);
    },
    [load],
  );

  const override = useCallback(
    async (row: ClassMethodRow) => {
      const doc = await load(row);
      if (!doc) return;
      setMode({ kind: "create", title: `Override ${row.method_name} in ${row.class_name}` });
      setFullDoc(null);
      setMethodDoc(overrideDraft(row, doc));
      setSession((n) => n + 1);
    },
    [load],
  );

  const createNew = useCallback(() => {
    seq.current++;
    setMode({ kind: "create", title: "New method" });
    setFullDoc(null);
    setMethodDoc({ impl_kind: "action" });
    setError(null);
    setStatus(null);
    setSession((n) => n + 1);
  }, []);

  const saveMethod = useCallback(
    async (edited: Record<string, unknown>) => {
      setError(null);
      setStatus("Saving…");
      try {
        const methodId = mode.kind === "edit" ? mode.methodId : null;
        const key = await saveRecordDocument(ENTITY, methodId != null ? String(methodId) : null, edited);
        await reload();
        const doc = await fetchRecordDocument(ENTITY, key);
        const savedRow: ClassMethodRow = {
          class_name: String(doc.class_name ?? ""),
          method_id: Number(key),
          method_name: String(doc.method_name ?? ""),
          declared_on_class: String(doc.class_name ?? ""),
          inherited: false,
          inheritance_depth: 0,
          is_override: Boolean(doc.is_override),
          is_abstract: doc.impl_kind === "abstract",
          is_final: Boolean(doc.is_final),
          impl_kind: typeof doc.impl_kind === "string" ? doc.impl_kind : null,
          impl_ref: typeof doc.action_name === "string" ? doc.action_name : null,
          description: null,
          param_count: Array.isArray(doc.parameters) ? doc.parameters.length : 0,
        };
        // Editing keeps the row that was opened (an inherited row stays inherited, so the
        // "applies to every class that inherits it" note and the list highlight stay correct).
        const nextRow = mode.kind === "edit" ? mode.row : savedRow;
        setMode({ kind: "edit", row: nextRow, methodId: Number(key) });
        setFullDoc(doc);
        setMethodDoc(editableDocument(CLASS_METHOD_EDIT_SCHEMA, doc));
        setSession((n) => n + 1);
        setStatus(`Saved ${savedRow.class_name}.${savedRow.method_name}; action catalog synchronised`);
      } catch (e) {
        setStatus(null);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [mode, reload],
  );

  const saveDefaults = useCallback(
    async (defaults: Record<string, unknown>) => {
      if (mode.kind !== "edit") return;
      setError(null);
      try {
        await runRecordEditorAction(ENTITY, "defaults", String(mode.methodId), defaults);
        setFullDoc((d) => (d ? { ...d, defaults } : d));
        setStatus("Saved parameter defaults");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [mode],
  );

  const selectedKey = mode.kind === "edit" ? `${mode.row.class_name}:${mode.methodId}` : null;
  const defaultsSchema =
    fullDoc && fullDoc.defaults_schema && typeof fullDoc.defaults_schema === "object"
      ? (fullDoc.defaults_schema as Record<string, unknown>)
      : null;
  const hasParams = Array.isArray(fullDoc?.parameters) && (fullDoc?.parameters as unknown[]).length > 0;
  const editingInherited = mode.kind === "edit" && mode.row.inherited;

  return (
    <section className="g-record-editor g-action-methods" data-testid="record-editor-class_method">
      <header className="g-record-editor__toolbar">
        <h3>Actions (class methods)</h3>
        <label>
          <span className="sr-only">Filter methods</span>
          <input
            type="search"
            placeholder="Filter by class, method or action"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </label>
        <button type="button" onClick={() => void reload()} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </button>
        <button type="button" onClick={createNew} data-testid="record-editor-new-class_method">
          New method
        </button>
      </header>
      {error ? (
        <p role="alert" className="g-record-editor__error">
          {error}
        </p>
      ) : null}
      {status ? <p role="status">{status}</p> : null}
      <div className="g-record-editor__body">
        <div className="g-action-methods__list">
          {groups.length === 0 ? <p>{loading ? "Loading…" : "No methods"}</p> : null}
          {groups.map((g) => (
            <details key={g.className} open={groups.length <= 8 || Boolean(filter)}>
              <summary>
                {g.className} <span className="g-badge">{g.methods.length}</span>
              </summary>
              <ul>
                {g.methods.map((m) => {
                  const key = `${m.class_name}:${m.method_id}`;
                  return (
                    <li key={key} className={key === selectedKey ? "is-selected" : undefined}>
                      <button
                        type="button"
                        onClick={() => void edit(m)}
                        aria-label={`Edit ${m.class_name}.${m.method_name}`}
                      >
                        {m.method_name}
                      </button>
                      <span className="g-badge">{methodOrigin(m)}</span>
                      {m.is_abstract ? <span className="g-badge">abstract</span> : null}
                      {m.is_final ? <span className="g-badge">final</span> : null}
                      {m.impl_ref ? <code>{m.impl_ref}</code> : null}
                      {m.inherited && !m.is_final ? (
                        <button
                          type="button"
                          onClick={() => void override(m)}
                          aria-label={`Override ${m.method_name} in ${m.class_name}`}
                        >
                          Override here
                        </button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </details>
          ))}
        </div>
        {methodDoc ? (
          <div className="g-record-editor__inspector" aria-label="method inspector">
            <h4>
              {mode.kind === "edit"
                ? `${String(fullDoc?.class_name ?? mode.row.declared_on_class)}.${mode.row.method_name}`
                : mode.kind === "create"
                  ? mode.title
                  : ""}
            </h4>
            {editingInherited ? (
              <p className="g-record-editor__note">
                Declared on {mode.row.declared_on_class}; changes apply to every class that inherits it. Use
                “Override here” to change it only for {mode.row.class_name}.
              </p>
            ) : null}
            <SchemaPropertyGrid
              key={`method:${selectedKey ?? "new"}:${session}`}
              fields={[]}
              flattenedSchema={mode.kind === "create" ? CLASS_METHOD_CREATE_SCHEMA : CLASS_METHOD_EDIT_SCHEMA}
              catalogResolver={catalogResolver}
              documentClassFqn="Method"
              initialDocument={methodDoc}
              onSubmit={saveMethod}
              submitLabel={mode.kind === "create" ? "Create method" : "Save method"}
            />
            {mode.kind === "edit" && hasParams && defaultsSchema ? (
              <div className="g-action-methods__defaults">
                <h5>Parameter defaults</h5>
                <SchemaPropertyGrid
                  key={`defaults:${selectedKey}:${session}`}
                  fields={[]}
                  flattenedSchema={defaultsSchema}
                  catalogResolver={catalogResolver}
                  documentClassFqn="Defaults"
                  initialDocument={(fullDoc?.defaults as Record<string, unknown>) ?? {}}
                  onSubmit={saveDefaults}
                  submitLabel="Save defaults"
                />
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}
