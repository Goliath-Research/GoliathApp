"use client";

import { createPlatformBffClient } from "@goliath/client";
import { RecordDialog, RecordGrid, SchemaPropertyGrid } from "@goliath/platform-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createHostMetaCatalogResolver } from "@/lib/meta-catalog-resolver";
import {
  editableDocument,
  mergeIdentityForSave,
  RECORD_EDITORS,
  type RecordEditorDefinition,
  viewSchemaFor,
} from "@/lib/record-editor-schemas";
import {
  fetchRecordDocument,
  fetchRecordRows,
  runRecordEditorAction,
  saveRecordDocument,
} from "@/lib/record-editor-client";

export type RecordEditorWorkspaceProps = {
  entity: keyof typeof RECORD_EDITORS | string;
};

type Mode = "view" | "edit" | "create";

/**
 * Generic record grid for one record-editor entity: toolbar Add, per-row View / Edit and the
 * entity's row actions. View and Edit open the typed property grid in a drawer; saves go through
 * the session-gated portal writers. Driven entirely by the entity's record-editor metadata.
 */
export function RecordEditorWorkspace({ entity }: RecordEditorWorkspaceProps) {
  const def: RecordEditorDefinition | undefined = RECORD_EDITORS[entity];
  const client = useMemo(() => createPlatformBffClient(), []);
  const catalogResolver = useMemo(() => createHostMetaCatalogResolver(client), [client]);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<Mode | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [document, setDocument] = useState<Record<string, unknown> | null>(null);
  const [original, setOriginal] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [session, setSession] = useState(0);
  const openSeq = useRef(0);

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

  const close = useCallback(() => {
    openSeq.current++;
    setMode(null);
    setDocument(null);
    setDialogError(null);
  }, []);

  const open = useCallback(
    async (row: Record<string, unknown>, next: "view" | "edit") => {
      if (!def) return;
      const key = def.rowKey(row);
      const seq = ++openSeq.current;
      setMode(next);
      setSelectedKey(key);
      setDocument(null);
      setDialogError(null);
      setStatus(null);
      try {
        const doc = await fetchRecordDocument(def.entity, key);
        if (seq !== openSeq.current) return;
        const merged = { ...row, ...doc };
        setOriginal(merged);
        setDocument(editableDocument(next === "view" ? viewSchemaFor(def) : def.editSchema, merged));
        setSession((n) => n + 1);
      } catch (e) {
        if (seq === openSeq.current) setDialogError(e instanceof Error ? e.message : String(e));
      }
    },
    [def],
  );

  const startNew = useCallback(() => {
    openSeq.current++;
    setSelectedKey(null);
    setOriginal(null);
    setMode("create");
    setDocument({});
    setDialogError(null);
    setStatus(null);
    setSession((n) => n + 1);
  }, []);

  const save = useCallback(
    async (edited: Record<string, unknown>) => {
      if (!def) return;
      setDialogError(null);
      try {
        const creating = mode === "create";
        const payload = mergeIdentityForSave(def.entity, selectedKey, original, edited);
        const key = await saveRecordDocument(def.entity, creating ? null : selectedKey, payload);
        setStatus(creating ? `Created ${def.noun} ${key}` : `Saved ${def.noun} ${key}`);
        setSelectedKey(key);
        close();
        await reload();
      } catch (e) {
        setDialogError(e instanceof Error ? e.message : String(e));
      }
    },
    [close, def, mode, original, reload, selectedKey],
  );

  const runAction = useCallback(
    async (action: string, row: Record<string, unknown>, label: string, confirmText?: string) => {
      if (!def) return;
      if (confirmText && !window.confirm(confirmText)) return;
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

  const selectedRow = rows.find((r) => def.rowKey(r) === selectedKey);
  const recordLabel = selectedRow ? def.rowLabel(selectedRow) : (selectedKey ?? "");
  const dialogTitle =
    mode === "create" ? `New ${def.noun}` : mode === "edit" ? `Edit ${recordLabel}` : `${recordLabel}`;
  const schema = mode === "create" ? def.createSchema : mode === "edit" ? def.editSchema : viewSchemaFor(def);

  return (
    <div className="g-record-editor" data-testid={`record-editor-${def.entity}`}>
      {error ? (
        <p role="alert" className="g-record-editor__error">
          {error}
        </p>
      ) : null}
      {status ? <p role="status">{status}</p> : null}
      <RecordGrid
        title={def.title}
        noun={def.noun}
        columns={def.columns}
        rows={rows}
        rowKey={def.rowKey}
        rowLabel={def.rowLabel}
        loading={loading}
        onRefresh={() => void reload()}
        onAdd={def.canCreate ? startNew : undefined}
        onView={(row) => void open(row, "view")}
        onEdit={(row) => void open(row, "edit")}
        canEdit={def.canEdit}
        selectedKey={mode ? selectedKey : null}
        testId={`record-grid-${def.entity}`}
        rowActions={(def.rowActions ?? []).map((a) => ({
          id: a.action,
          label: a.label,
          visible: a.visible,
          onRun: (row) => void runAction(a.action, row, a.label, a.confirm),
        }))}
      />
      <RecordDialog open={mode != null} title={dialogTitle} onClose={close} testId={`record-dialog-${def.entity}`}>
        {dialogError ? <p role="alert">{dialogError}</p> : null}
        {document ? (
          <div aria-label={`${def.noun} inspector`}>
            <SchemaPropertyGrid
              key={`${def.entity}:${selectedKey ?? "new"}:${mode}:${session}`}
              fields={[]}
              flattenedSchema={schema}
              catalogResolver={catalogResolver}
              documentClassFqn={def.title}
              initialDocument={document}
              disabled={mode === "view"}
              onSubmit={mode === "view" ? undefined : save}
              submitLabel={mode === "create" ? `Create ${def.noun}` : "Save changes"}
            />
            {mode === "view" && (def.canEdit == null || (selectedRow && def.canEdit(selectedRow))) ? (
              <button
                type="button"
                className="g-host-button"
                onClick={() => selectedRow && void open(selectedRow, "edit")}
                disabled={!selectedRow}
              >
                Edit
              </button>
            ) : null}
          </div>
        ) : dialogError ? null : (
          <p role="status">Loading…</p>
        )}
      </RecordDialog>
    </div>
  );
}
