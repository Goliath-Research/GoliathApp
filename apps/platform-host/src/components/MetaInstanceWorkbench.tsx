"use client";

import type { MetaClassField, MetaClassLineageNode, MetaObjectListRow } from "@goliath/client";
import { createPlatformBffClient } from "@goliath/client";
import { RecordDialog, RecordGrid, SchemaPropertyGrid } from "@goliath/platform-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EXAMPLE_CHILD_EXTENSION } from "@/lib/child-extension";
import { hierarchyRegistryFromManifest } from "@/lib/hierarchy-registry";
import {
  createHostMetaCatalogResolver,
  type MetaCatalogClassFixture,
} from "@/lib/meta-catalog-resolver";
import { MetaObjectSecurityPanel } from "./MetaObjectSecurityPanel";

const INSTANCE_COLUMNS = [
  { key: "objId", label: "ID" },
  { key: "displayLabel", label: "Label" },
  { key: "className", label: "Class" },
  { key: "updatedAtUtc", label: "Updated" },
];

export type MetaInstanceWorkbenchProps = {
  className: string;
  fields: MetaClassField[];
  flattenedSchema: unknown;
  bundledSchema?: unknown;
  lineage?: MetaClassLineageNode[];
  catalogClassFixtures?: Record<string, MetaCatalogClassFixture>;
  roles?: Array<{ role_id: number; role_name: string }>;
};

export function MetaInstanceWorkbench({
  className,
  fields,
  flattenedSchema,
  bundledSchema,
  lineage,
  catalogClassFixtures,
  roles = [],
}: MetaInstanceWorkbenchProps) {
  const client = useMemo(() => createPlatformBffClient(), []);
  const catalogResolver = useMemo(
    () => createHostMetaCatalogResolver(client, catalogClassFixtures),
    [client, catalogClassFixtures],
  );
  const registry = useMemo(
    () => hierarchyRegistryFromManifest(EXAMPLE_CHILD_EXTENSION.manifest),
    [],
  );

  const [listRows, setListRows] = useState<MetaObjectListRow[]>([]);
  const [includeSubclasses, setIncludeSubclasses] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  /** Open drawer: view / edit an object, or create a new one. */
  const [mode, setMode] = useState<"view" | "edit" | "create" | null>(null);
  const [selectedObjId, setSelectedObjId] = useState<number | null>(null);
  const [editorDocument, setEditorDocument] = useState<Record<string, unknown> | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [session, setSession] = useState(0);
  const openSeq = useRef(0);

  const refreshList = useCallback(async () => {
    setListLoading(true);
    setError(null);
    try {
      setListRows(await client.listMetaObjects(className, { includeSubclasses, limit: 100 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load instances");
    } finally {
      setListLoading(false);
    }
  }, [className, client, includeSubclasses]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const close = useCallback(() => {
    openSeq.current++;
    setMode(null);
    setEditorDocument(null);
    setDialogError(null);
  }, []);

  async function openObject(objId: number, next: "view" | "edit") {
    const seq = ++openSeq.current;
    setMode(next);
    setSelectedObjId(objId);
    setEditorDocument(null);
    setDialogError(null);
    setStatus(null);
    try {
      const row = await client.getMetaObject(objId);
      if (seq !== openSeq.current) return;
      setEditorDocument(row.document ?? {});
      setSession((n) => n + 1);
    } catch (e) {
      if (seq === openSeq.current) setDialogError(e instanceof Error ? e.message : "failed to load object");
    }
  }

  function handleNew() {
    openSeq.current++;
    setSelectedObjId(null);
    setMode("create");
    setEditorDocument({});
    setDialogError(null);
    setStatus(null);
    setSession((n) => n + 1);
  }

  async function save(document: Record<string, unknown>) {
    const seq = ++openSeq.current;
    const targetObjId = mode === "edit" ? selectedObjId : null;
    const base = editorDocument ?? {};
    setDialogError(null);
    try {
      if (targetObjId != null) {
        await client.updateMetaObject(targetObjId, { ...base, ...document });
        setStatus(`Updated object #${targetObjId}.`);
      } else {
        const { objId } = await client.createMetaObject(className, document);
        setSelectedObjId(objId);
        setStatus(`Created object #${objId}.`);
      }
      if (seq === openSeq.current) close();
      await refreshList();
    } catch (e) {
      if (seq === openSeq.current) setDialogError(e instanceof Error ? e.message : "save failed");
    }
  }

  const gridRows = useMemo(
    () =>
      listRows.map((r) => ({
        objId: r.objId,
        displayLabel: r.displayLabel,
        className: r.className,
        updatedAtUtc: r.updatedAtUtc,
      })),
    [listRows],
  );
  const selectedRow = gridRows.find((r) => r.objId === selectedObjId);
  const recordLabel = selectedRow?.displayLabel || (selectedObjId != null ? `#${selectedObjId}` : "");

  return (
    <div className="g-meta-workbench" data-testid="meta-instance-workbench">
      {error ? (
        <p role="alert" className="g-meta-workbench__error">
          {error}
        </p>
      ) : null}
      {status ? (
        <p role="status" data-testid="meta-workbench-status">
          {status}
        </p>
      ) : null}
      <RecordGrid
        title="Instances"
        noun="instance"
        columns={INSTANCE_COLUMNS}
        rows={gridRows}
        rowKey={(r) => String(r.objId)}
        rowLabel={(r) => (r.displayLabel ? `${r.displayLabel} (#${r.objId})` : `#${r.objId}`)}
        rowTestId={(r) => `meta-instance-row-${r.objId}`}
        loading={listLoading}
        onRefresh={() => void refreshList()}
        onAdd={handleNew}
        onView={(r) => void openObject(r.objId, "view")}
        onEdit={(r) => void openObject(r.objId, "edit")}
        selectedKey={mode && selectedObjId != null ? String(selectedObjId) : null}
        testId="meta-instance-list"
        emptyText="No instances in this scope yet."
        toolbarSlot={
          <label className="g-meta-instance-list__toggle">
            <input
              type="checkbox"
              checked={includeSubclasses}
              onChange={(e) => setIncludeSubclasses(e.target.checked)}
            />
            Include subclasses
          </label>
        }
      />
      <RecordDialog
        open={mode != null}
        title={mode === "create" ? `New ${className}` : mode === "edit" ? `Edit ${recordLabel}` : recordLabel}
        onClose={close}
        testId="meta-instance-dialog"
      >
        {dialogError ? <p role="alert">{dialogError}</p> : null}
        {editorDocument ? (
          <>
            <SchemaPropertyGrid
              key={`${className}:${selectedObjId ?? "new"}:${mode}:${session}`}
              fields={fields}
              flattenedSchema={flattenedSchema}
              bundledSchema={bundledSchema}
              lineage={lineage}
              registry={registry}
              catalogResolver={catalogResolver}
              documentClassFqn={className}
              initialDocument={editorDocument}
              disabled={mode === "view"}
              onSubmit={mode === "view" ? undefined : save}
              submitLabel={mode === "edit" ? "Save changes" : "Create instance"}
            />
            {mode === "view" && selectedObjId != null ? (
              <button type="button" className="g-host-button" onClick={() => void openObject(selectedObjId, "edit")}>
                Edit
              </button>
            ) : null}
            {mode !== "create" && selectedObjId != null && roles.length > 0 ? (
              <MetaObjectSecurityPanel objId={selectedObjId} roles={roles} />
            ) : null}
          </>
        ) : dialogError ? null : (
          <p role="status">Loading…</p>
        )}
      </RecordDialog>
    </div>
  );
}
