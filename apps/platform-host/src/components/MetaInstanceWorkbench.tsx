"use client";

import type { MetaClassField, MetaClassLineageNode, MetaObjectListRow } from "@goliath/client";
import { createPlatformBffClient } from "@goliath/client";
import { RecordDialog, RecordGrid, RecordTree, SchemaPropertyGrid, type RecordTreeNode } from "@goliath/platform-ui";
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
  /** Class has a hierarchical self relation: show the generic tree editor instead of the grid. */
  tree?: boolean;
};

type TreeRow = { objId: number; parentObjId: number | null; className: string; displayLabel: string; childCount: number };

async function treeRequest(body: Record<string, unknown>): Promise<void> {
  const res = await fetch("/api/portal/meta-tree", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const payload = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(payload.error ?? `Tree update failed (${res.status})`);
  }
}

export function MetaInstanceWorkbench({
  className,
  fields,
  flattenedSchema,
  bundledSchema,
  lineage,
  catalogClassFixtures,
  roles = [],
  tree = false,
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

  const [treeRows, setTreeRows] = useState<TreeRow[]>([]);
  /** Where a node created from the tree goes (parent object, sibling position). */
  const placement = useRef<{ parent: number | null; position: number | null } | null>(null);

  const refreshList = useCallback(async () => {
    setListLoading(true);
    setError(null);
    try {
      if (tree) {
        const res = await fetch(`/api/portal/meta-tree?class=${encodeURIComponent(className)}`, {
          credentials: "same-origin",
        });
        const body = (await res.json().catch(() => ({}))) as { rows?: TreeRow[]; error?: string };
        if (!res.ok) throw new Error(body.error ?? `failed to load tree (${res.status})`);
        setTreeRows(body.rows ?? []);
        return;
      }
      setListRows(await client.listMetaObjects(className, { includeSubclasses, limit: 100 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load instances");
    } finally {
      setListLoading(false);
    }
  }, [className, client, includeSubclasses, tree]);

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

  function handleNew(where: { parent: number | null; position: number | null } | null = null) {
    placement.current = where;
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
        if (tree) {
          const where = placement.current ?? { parent: null, position: null };
          await treeRequest({ action: "move", className, objId, parentObjId: where.parent, position: where.position });
        }
        setStatus(`Created object #${objId}.`);
      }
      if (seq === openSeq.current) close();
      await refreshList();
    } catch (e) {
      if (seq === openSeq.current) setDialogError(e instanceof Error ? e.message : "save failed");
    }
  }

  const treeNodes = useMemo(
    (): RecordTreeNode[] =>
      treeRows.map((r) => ({
        key: String(r.objId),
        parentKey: r.parentObjId == null ? null : String(r.parentObjId),
        label: r.displayLabel || `#${r.objId}`,
        detail: r.className !== className ? r.className : undefined,
      })),
    [treeRows, className],
  );

  async function treeAction(body: Record<string, unknown>, done: string) {
    setError(null);
    try {
      await treeRequest({ className, ...body });
      setStatus(done);
      await refreshList();
    } catch (e) {
      setError(e instanceof Error ? e.message : "tree update failed");
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
      {tree ? (
        <RecordTree
          title="Tree"
          noun="node"
          nodes={treeNodes}
          loading={listLoading}
          selectedKey={mode && selectedObjId != null ? String(selectedObjId) : null}
          testId="meta-tree"
          onRefresh={() => void refreshList()}
          onView={(n) => void openObject(Number(n.key), "view")}
          onEdit={(n) => void openObject(Number(n.key), "edit")}
          onAddChild={(parent) => handleNew({ parent: parent ? Number(parent.key) : null, position: null })}
          onAddSibling={(sib) => {
            const siblings = treeNodes.filter((n) => n.parentKey === sib.parentKey);
            handleNew({
              parent: sib.parentKey == null ? null : Number(sib.parentKey),
              position: siblings.findIndex((n) => n.key === sib.key) + 1,
            });
          }}
          onMove={(n, parentKey, position) =>
            void treeAction(
              {
                action: "move",
                objId: Number(n.key),
                parentObjId: parentKey == null ? null : Number(parentKey),
                position,
              },
              `Moved ${n.label}.`,
            )
          }
          canDelete={(_n, kids) => kids === 0}
          onDelete={(n) => {
            if (!window.confirm(`Delete ${n.label}?`)) return;
            void treeAction({ action: "delete", objId: Number(n.key) }, `Deleted ${n.label}.`);
          }}
        />
      ) : (
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
          onAdd={() => handleNew()}
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
      )}
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
