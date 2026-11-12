"use client";

import type { MetaClassField } from "@goliath/client";
import type { ReactNode } from "react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { CatalogRef } from "./catalogRef.js";
import { isSchemaRecord, SCHEMA_PROPERTY_GRID_MAX_DEPTH, syntheticFieldsFromSchema } from "./jsonSchema.js";
import type { MetaCatalogResolver } from "./metaCatalogResolver.js";
import {
  resolveClassGridPresentation,
  type HierarchyPresentationRegistry,
} from "./metaHierarchyResolver.js";
import { parseGoliathRef } from "./catalogRef.js";
import { lazy, Suspense } from "react";
import { PropertyInspectorModal } from "./PropertyInspectorModal.js";

const LazySchemaPropertyGridSurface = lazy(() =>
  import("./SchemaPropertyGridSurface.js").then((m) => ({ default: m.SchemaPropertyGridSurface })),
);

const EMPTY_OBJECT_SCHEMA: Record<string, unknown> = { type: "object", properties: {} };

export type CatalogNestedSchemaDialogProps = {
  title: string;
  catalogTarget: CatalogRef;
  catalogResolver: MetaCatalogResolver;
  registry: HierarchyPresentationRegistry;
  bundledSchema?: unknown;
  initialValue: Record<string, unknown>;
  depth: number;
  headerSlot?: ReactNode;
  onSave: (value: Record<string, unknown>) => void;
  onCancel: () => void;
  breadcrumb?: readonly string[];
  usePropertyInspectorChrome?: boolean;
};

export function CatalogNestedSchemaDialog({
  title,
  catalogTarget,
  catalogResolver,
  registry,
  bundledSchema,
  initialValue,
  depth,
  headerSlot,
  onSave,
  onCancel,
  breadcrumb,
  usePropertyInspectorChrome = false,
}: CatalogNestedSchemaDialogProps) {
  const titleId = useId();
  const commitSnapshotRef = useRef<(() => Record<string, unknown>) | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<MetaClassField[] | undefined>();
  const [flattened, setFlattened] = useState<unknown>(undefined);
  const [bundled, setBundled] = useState<unknown>(bundledSchema);
  const [classAncestry, setClassAncestry] = useState<readonly string[]>([]);
  const [gridHeader, setGridHeader] = useState<ReactNode>(headerSlot);

  useEffect(() => {
    if (usePropertyInspectorChrome) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, usePropertyInspectorChrome]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        if (catalogTarget.kind === "metaClass") {
          const ctx = await catalogResolver.loadMetaClass(catalogTarget.className);
          if (cancelled) return;
          const ancestry = ctx.lineage
            .filter((n) => n.lineageRole === "ancestor" || n.lineageRole === "self")
            .sort((a, b) => b.depth - a.depth)
            .map((n) => n.className);
          setClassAncestry(ancestry);
          setFields(ctx.fields);
          setFlattened(ctx.flattenedSchema);
          setBundled(ctx.bundledSchema);
          const presentation = resolveClassGridPresentation(catalogTarget.className, ancestry, registry);
          if (presentation.icon) {
            setGridHeader(
              <p className="g-host-home__lead" data-testid="nested-grid-icon">
                icon:{presentation.icon}
              </p>,
            );
          }
        } else if (catalogTarget.kind === "dataType") {
          const dt = await catalogResolver.loadDataType(catalogTarget.typeName);
          if (cancelled) return;
          let schema = dt.schemaJson;
          if (isSchemaRecord(schema) && typeof schema.$ref === "string") {
            const ref = parseGoliathRef(schema.$ref);
            if (ref?.kind === "metaClass") {
              const ctx = await catalogResolver.loadMetaClass(ref.className);
              if (cancelled) return;
              const ancestry = ctx.lineage
                .filter((n) => n.lineageRole === "ancestor" || n.lineageRole === "self")
                .sort((a, b) => b.depth - a.depth)
                .map((n) => n.className);
              setClassAncestry(ancestry);
              setFields(ctx.fields);
              setFlattened(ctx.flattenedSchema);
              setBundled(ctx.bundledSchema);
              return;
            }
          }
          if (isSchemaRecord(schema)) {
            setFlattened(schema);
            setBundled(schema);
            setFields(undefined);
          } else {
            throw new Error(`data type ${catalogTarget.typeName} has no object schema`);
          }
        } else {
          throw new Error("inline nested catalog is not loaded asynchronously");
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "failed to load nested schema");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [catalogTarget, catalogResolver, registry, bundledSchema]);

  const root = useMemo(
    () => (isSchemaRecord(bundled) ? bundled : isSchemaRecord(flattened) ? flattened : EMPTY_OBJECT_SCHEMA),
    [bundled, flattened],
  );

  const syntheticFields = useMemo(
    () =>
      fields ? undefined : syntheticFieldsFromSchema(isSchemaRecord(flattened) ? flattened : root, root),
    [fields, flattened, root],
  );

  const declaringClassAncestryByField = useMemo(
    () =>
      fields
        ? Object.fromEntries(
            fields.map((f) => [f.fieldName, classAncestry.length ? classAncestry : [f.declaredOnClassName]]),
          )
        : undefined,
    [fields, classAncestry],
  );

  if (depth >= SCHEMA_PROPERTY_GRID_MAX_DEPTH) {
    return (
      <DialogBackdrop onCancel={onCancel}>
        <div className="g-schema-dialog" role="alertdialog" aria-labelledby={titleId}>
          <h3 id={titleId}>{title}</h3>
          <p>Maximum nesting depth ({SCHEMA_PROPERTY_GRID_MAX_DEPTH}) reached.</p>
          <button type="button" className="g-host-button" onClick={onCancel}>
            Close
          </button>
        </div>
      </DialogBackdrop>
    );
  }

  const grid = !loading && !error && flattened != null ? (
    <Suspense fallback={<p>Loading nested grid…</p>}>
      <LazySchemaPropertyGridSurface
        fields={fields}
        syntheticFields={syntheticFields}
        schema={flattened}
        rootSchema={fields != null ? root : isSchemaRecord(flattened) ? flattened : root}
        bundledSchema={bundled}
        registry={registry}
        catalogResolver={catalogResolver}
        documentClassFqn={catalogTarget.kind === "metaClass" ? catalogTarget.className : undefined}
        declaringClassAncestryByField={declaringClassAncestryByField}
        initialDocument={initialValue}
        depth={depth}
        embedded
        headerSlot={gridHeader ?? headerSlot}
        commitSnapshotRef={commitSnapshotRef}
        breadcrumbBase={breadcrumb}
        onSubmit={usePropertyInspectorChrome ? undefined : onSave}
        submitLabel={usePropertyInspectorChrome ? undefined : "Save"}
      />
    </Suspense>
  ) : null;

  if (usePropertyInspectorChrome) {
    return (
      <PropertyInspectorModal
        open
        title={title}
        breadcrumb={breadcrumb}
        onOk={() => onSave(commitSnapshotRef.current?.() ?? initialValue)}
        onCancel={onCancel}
        okDisabled={loading || !!error || flattened == null}
      >
        {loading ? <p>Loading nested class schema…</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        {grid}
      </PropertyInspectorModal>
    );
  }

  return (
    <DialogBackdrop onCancel={onCancel}>
      <dialog open className="g-schema-dialog" data-testid="schema-nested-dialog" aria-labelledby={titleId}>
        <h3 id={titleId}>{title}</h3>
        {loading ? <p>Loading nested class schema…</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        {grid}
        <div className="g-schema-dialog__actions">
          <button type="button" className="g-host-button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </dialog>
    </DialogBackdrop>
  );
}

function DialogBackdrop({ children, onCancel }: { children: ReactNode; onCancel: () => void }) {
  return (
    <div className="g-schema-dialog-backdrop">
      <button type="button" className="g-schema-dialog-backdrop__hit" aria-label="Close dialog" onClick={onCancel} />
      {children}
    </div>
  );
}
