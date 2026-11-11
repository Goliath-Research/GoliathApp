"use client";

import type { MetaClassField, MetaClassLineageNode, MetaObjectListRow } from "@goliath/client";
import { createPlatformBffClient } from "@goliath/client";
import { SchemaPropertyGrid } from "@goliath/platform-ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EXAMPLE_CHILD_EXTENSION } from "@/lib/child-extension";
import { hierarchyRegistryFromManifest } from "@/lib/hierarchy-registry";
import {
  createHostMetaCatalogResolver,
  type MetaCatalogClassFixture,
} from "@/lib/meta-catalog-resolver";
import { MetaInstanceObjectList } from "./MetaInstanceObjectList";
import { MetaObjectSecurityPanel } from "./MetaObjectSecurityPanel";

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
  const [selectedObjId, setSelectedObjId] = useState<number | null>(null);
  const [editorDocument, setEditorDocument] = useState<Record<string, unknown>>({});
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const gridKey = selectedObjId == null ? `new:${className}` : `obj:${selectedObjId}`;
  const selectRequestRef = useRef(0);
  const saveRequestRef = useRef(0);

  const refreshList = useCallback(async () => {
    setListLoading(true);
    setError(null);
    try {
      const rows = await client.listMetaObjects(className, { includeSubclasses, limit: 100 });
      setListRows(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to load instances");
    } finally {
      setListLoading(false);
    }
  }, [className, client, includeSubclasses]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  async function handleSelect(objId: number) {
    setStatus(null);
    setError(null);
    ++saveRequestRef.current;
    const requestId = ++selectRequestRef.current;
    try {
      const row = await client.getMetaObject(objId);
      if (requestId !== selectRequestRef.current) return;
      setEditorDocument(row.document ?? {});
      setSelectedObjId(objId);
    } catch (e) {
      if (requestId !== selectRequestRef.current) return;
      setError(e instanceof Error ? e.message : "failed to load object");
    }
  }

  function handleNew() {
    ++saveRequestRef.current;
    ++selectRequestRef.current;
    setSelectedObjId(null);
    setEditorDocument({});
    setStatus("Create mode — fill properties and save.");
    setError(null);
  }

  async function save(document: Record<string, unknown>) {
    const saveId = ++saveRequestRef.current;
    const targetObjId = selectedObjId;
    setStatus(null);
    setError(null);
    try {
      if (targetObjId != null) {
        const payload = { ...editorDocument, ...document };
        await client.updateMetaObject(targetObjId, payload);
        await refreshList();
        if (saveId !== saveRequestRef.current) return;
        const row = await client.getMetaObject(targetObjId);
        if (saveId !== saveRequestRef.current) return;
        if (selectedObjId !== targetObjId) return;
        setEditorDocument(row.document ?? {});
        setSelectedObjId(targetObjId);
        setStatus(`Updated object #${targetObjId}.`);
        return;
      }
      const { objId } = await client.createMetaObject(className, document);
      await refreshList();
      if (saveId !== saveRequestRef.current) return;
      const row = await client.getMetaObject(objId);
      if (saveId !== saveRequestRef.current) return;
      setEditorDocument(row.document ?? {});
      setSelectedObjId(objId);
      setStatus(`Created object #${objId}.`);
    } catch (e) {
      if (saveId !== saveRequestRef.current) return;
      setError(e instanceof Error ? e.message : "save failed");
    }
  }

  return (
    <div className="g-meta-workbench" data-testid="meta-instance-workbench">
      <MetaInstanceObjectList
        rows={listRows}
        selectedObjId={selectedObjId}
        includeSubclasses={includeSubclasses}
        loading={listLoading}
        onToggleSubclasses={setIncludeSubclasses}
        onSelect={handleSelect}
        onNew={handleNew}
      />
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
      <SchemaPropertyGrid
        key={gridKey}
        fields={fields}
        flattenedSchema={flattenedSchema}
        bundledSchema={bundledSchema}
        lineage={lineage}
        registry={registry}
        catalogResolver={catalogResolver}
        documentClassFqn={className}
        initialDocument={editorDocument}
        onSubmit={save}
        submitLabel={selectedObjId != null ? "Save changes" : "Create instance"}
      />
      {selectedObjId != null && roles.length > 0 ? (
        <MetaObjectSecurityPanel objId={selectedObjId} roles={roles} />
      ) : null}
    </div>
  );
}
