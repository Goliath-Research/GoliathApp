"use client";

import type { ReactNode } from "react";
import { lazy, Suspense, useEffect, useId, useState } from "react";
import type { SyntheticSchemaField } from "./jsonSchema.js";
import { SCHEMA_PROPERTY_GRID_MAX_DEPTH } from "./jsonSchema.js";
import type { MetaCatalogResolver } from "./metaCatalogResolver.js";
import type { HierarchyPresentationRegistry } from "./metaHierarchyResolver.js";

const LazySchemaPropertyGridSurface = lazy(() =>
  import("./SchemaPropertyGridSurface.js").then((m) => ({ default: m.SchemaPropertyGridSurface })),
);

export type NestedSchemaDialogProps = {
  title: string;
  objectSchema: Record<string, unknown>;
  rootSchema: Record<string, unknown>;
  bundledSchema?: unknown;
  registry?: HierarchyPresentationRegistry;
  catalogResolver?: MetaCatalogResolver;
  initialValue: Record<string, unknown>;
  depth: number;
  onSave: (value: Record<string, unknown>) => void;
  onCancel: () => void;
};

export function NestedSchemaDialog({
  title,
  objectSchema,
  rootSchema,
  bundledSchema,
  registry,
  catalogResolver,
  initialValue,
  depth,
  onSave,
  onCancel,
}: NestedSchemaDialogProps) {
  const titleId = useId();
  const [draft, setDraft] = useState<Record<string, unknown>>(initialValue);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      onCancel();
    };
    window.addEventListener("keydown", onKey, { capture: true });
    return () => window.removeEventListener("keydown", onKey, { capture: true });
  }, [onCancel]);

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

  const syntheticFields: SyntheticSchemaField[] = Object.keys(
    (objectSchema.properties as Record<string, unknown> | undefined) ?? {},
  )
    .sort()
    .map((fieldName) => ({
      fieldName,
      required: Array.isArray(objectSchema.required)
        ? (objectSchema.required as string[]).includes(fieldName)
        : false,
    }));

  return (
    <DialogBackdrop onCancel={onCancel}>
      <div className="g-schema-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h3 id={titleId}>{title}</h3>
        <Suspense fallback={<p>Loading nested grid…</p>}>
          <LazySchemaPropertyGridSurface
            syntheticFields={syntheticFields}
            schema={objectSchema}
            rootSchema={rootSchema}
            bundledSchema={bundledSchema ?? rootSchema}
            registry={registry}
            catalogResolver={catalogResolver}
            initialDocument={draft}
            depth={depth}
            submitLabel="Save"
            embedded
            onDraftChange={setDraft}
            onSubmit={(document) => {
              setError(null);
              onSave(document);
            }}
          />
        </Suspense>
        {error ? <p role="alert">{error}</p> : null}
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
    <div className="g-schema-dialog-backdrop" data-testid="schema-nested-dialog">
      <button type="button" className="g-schema-dialog-backdrop__hit" aria-label="Close dialog" onClick={onCancel} />
      {children}
    </div>
  );
}
