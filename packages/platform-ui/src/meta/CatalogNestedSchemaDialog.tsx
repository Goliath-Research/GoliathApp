"use client";

import type { MetaClassField } from "@goliath/client";
import type { ReactNode } from "react";
import { useEffect, useId, useState } from "react";
import type { CatalogRef } from "./catalogRef.js";
import { isSchemaRecord, SCHEMA_PROPERTY_GRID_MAX_DEPTH, syntheticFieldsFromSchema } from "./jsonSchema.js";
import type { MetaCatalogResolver } from "./metaCatalogResolver.js";
import {
  resolveClassGridPresentation,
  type HierarchyPresentationRegistry,
} from "./metaHierarchyResolver.js";
import { parseGoliathRef } from "./catalogRef.js";
import { lazy, Suspense } from "react";

const LazySchemaPropertyGridSurface = lazy(() =>
  import("./SchemaPropertyGridSurface.js").then((m) => ({ default: m.SchemaPropertyGridSurface })),
);

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
}: CatalogNestedSchemaDialogProps) {
  const titleId = useId();
  const [draft, setDraft] = useState(initialValue);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<MetaClassField[] | undefined>();
  const [flattened, setFlattened] = useState<unknown>(undefined);
  const [bundled, setBundled] = useState<unknown>(bundledSchema);
  const [classAncestry, setClassAncestry] = useState<readonly string[]>([]);
  const [gridHeader, setGridHeader] = useState<ReactNode>(headerSlot);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

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
            setBundled(bundledSchema ?? schema);
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

  const root =
    isSchemaRecord(bundled) ? bundled : isSchemaRecord(flattened) ? flattened : { type: "object", properties: {} };

  return (
    <DialogBackdrop onCancel={onCancel}>
      <div className="g-schema-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h3 id={titleId}>{title}</h3>
        {loading ? <p>Loading nested class schema…</p> : null}
        {error ? <p role="alert">{error}</p> : null}
        {!loading && !error && flattened != null ? (
          <Suspense fallback={<p>Loading nested grid…</p>}>
            <LazySchemaPropertyGridSurface
              fields={fields}
              syntheticFields={
                fields ? undefined : syntheticFieldsFromSchema(root, root)
              }
              schema={flattened}
              rootSchema={root}
              bundledSchema={bundled}
              registry={registry}
              catalogResolver={catalogResolver}
              documentClassFqn={catalogTarget.kind === "metaClass" ? catalogTarget.className : undefined}
              declaringClassAncestryByField={
                fields
                  ? Object.fromEntries(
                      fields.map((f) => [f.fieldName, classAncestry.length ? classAncestry : [f.declaredOnClassName]]),
                    )
                  : undefined
              }
              initialDocument={draft}
              depth={depth}
              submitLabel="Save"
              embedded
              headerSlot={gridHeader ?? headerSlot}
              onDraftChange={setDraft}
              onSubmit={onSave}
            />
          </Suspense>
        ) : null}
        <div className="g-schema-dialog__actions">
          <button type="button" className="g-host-button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
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
