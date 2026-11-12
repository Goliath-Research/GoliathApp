"use client";

import { lazy, Suspense, useCallback, useMemo, useRef } from "react";
import type { CatalogRef } from "./catalogRef.js";
import { CatalogNestedSchemaDialog } from "./CatalogNestedSchemaDialog.js";
import { isSchemaRecord, syntheticFieldsFromSchema } from "./jsonSchema.js";
import type { MetaCatalogResolver } from "./metaCatalogResolver.js";
import type { HierarchyPresentationRegistry } from "./metaHierarchyResolver.js";
import { PropertyInspectorModal } from "./PropertyInspectorModal.js";
const LazySchemaPropertyGridSurface = lazy(() =>
  import("./SchemaPropertyGridSurface.js").then((m) => ({ default: m.SchemaPropertyGridSurface })),
);

export type InspectorDialogRequest =
  | {
      kind: "catalog";
      fieldName: string;
      catalogTarget: CatalogRef;
      value: Record<string, unknown>;
      breadcrumb: string[];
      arrayIndex?: number;
      isNew?: boolean;
    }
  | {
      kind: "object";
      fieldName: string;
      objectSchema: Record<string, unknown>;
      rootSchema: Record<string, unknown>;
      value: Record<string, unknown>;
      breadcrumb: string[];
    }
  | {
      kind: "array-item";
      fieldName: string;
      objectSchema: Record<string, unknown>;
      rootSchema: Record<string, unknown>;
      value: Record<string, unknown>;
      index: number;
      isNew: boolean;
      breadcrumb: string[];
    }
  | null;

type PropertyInspectorDialogHostProps = {
  request: InspectorDialogRequest;
  catalogResolver?: MetaCatalogResolver;
  registry?: HierarchyPresentationRegistry;
  bundledSchema?: unknown;
  depth: number;
  onCommit: (value: Record<string, unknown>) => void;
  onDismiss: () => void;
};

/** Portal modal host: OK/Cancel, breadcrumb, embedded hierarchy grid (Delphi inspector popup). */
export function PropertyInspectorDialogHost({
  request,
  catalogResolver,
  registry,
  bundledSchema,
  depth,
  onCommit,
  onDismiss,
}: PropertyInspectorDialogHostProps) {
  if (!request) return null;

  if (request.kind === "catalog" && catalogResolver) {
    return (
      <CatalogNestedSchemaDialog
        title={request.fieldName}
        breadcrumb={request.breadcrumb}
        catalogTarget={request.catalogTarget}
        catalogResolver={catalogResolver}
        registry={registry ?? { editorComponentsByClassFqn: {}, iconOverridesByClassFqn: {} }}
        bundledSchema={bundledSchema}
        initialValue={request.value}
        depth={depth + 1}
        onSave={onCommit}
        onCancel={onDismiss}
        usePropertyInspectorChrome
      />
    );
  }

  return (
    <ObjectInspectorModalBody
      request={request}
      catalogResolver={catalogResolver}
      registry={registry}
      bundledSchema={bundledSchema}
      depth={depth}
      onCommit={onCommit}
      onDismiss={onDismiss}
    />
  );
}

function ObjectInspectorModalBody({
  request,
  catalogResolver,
  registry,
  bundledSchema,
  depth,
  onCommit,
  onDismiss,
}: PropertyInspectorDialogHostProps & { request: NonNullable<InspectorDialogRequest> }) {
  const commitSnapshotRef = useRef<(() => Record<string, unknown>) | undefined>(undefined);
  const objectSchema = request.kind === "object" || request.kind === "array-item" ? request.objectSchema : {};
  const rootSchema = request.kind === "object" || request.kind === "array-item" ? request.rootSchema : objectSchema;

  const syntheticFields = useMemo(() => {
    if (!isSchemaRecord(objectSchema)) return [];
    return syntheticFieldsFromSchema(objectSchema, rootSchema);
  }, [objectSchema, rootSchema]);

  const title =
    request.kind === "array-item"
      ? `${request.isNew ? "Add" : "Edit"} ${request.fieldName}[${request.index}]`
      : request.fieldName;

  const onOk = useCallback(
    () => onCommit(commitSnapshotRef.current?.() ?? request.value),
    [onCommit, request.value],
  );

  return (
    <PropertyInspectorModal
      open
      title={title}
      breadcrumb={request.breadcrumb}
      onOk={onOk}
      onCancel={onDismiss}
    >
      <Suspense fallback={<p>Loading properties…</p>}>
        <LazySchemaPropertyGridSurface
          syntheticFields={syntheticFields}
          schema={objectSchema}
          rootSchema={rootSchema}
          bundledSchema={bundledSchema ?? rootSchema}
          registry={registry}
          catalogResolver={catalogResolver}
          initialDocument={request.value}
          depth={depth + 1}
          embedded
          commitSnapshotRef={commitSnapshotRef}
        />
      </Suspense>
    </PropertyInspectorModal>
  );
}
