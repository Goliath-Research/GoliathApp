"use client";

/**
 * SchemaPropertyGrid — hierarchy-driven vertical property grid (Meta class / wf.data_type first).
 * SQL contract: `workflow_engine/sql_pg/wf_data_type.sql` (SchemaPropertyGrid binds schema_json).
 * Resolution: `metaHierarchyResolver.ts` (ancestry walk for editors, icons, nested catalog loads).
 */

import type { MetaClassField, MetaClassLineageNode } from "@goliath/client";
import type { ReactNode } from "react";
import { useMemo } from "react";
import { isSchemaRecord } from "./jsonSchema.js";
import type { MetaCatalogResolver } from "./metaCatalogResolver.js";
import type { HierarchyPresentationRegistry } from "./metaHierarchyResolver.js";
import { SchemaPropertyGridSurface } from "./SchemaPropertyGridSurface.js";

export type SchemaPropertyGridProps = {
  fields: MetaClassField[];
  flattenedSchema: unknown;
  bundledSchema?: unknown;
  lineage?: MetaClassLineageNode[];
  registry?: HierarchyPresentationRegistry;
  catalogResolver?: MetaCatalogResolver;
  initialDocument?: Record<string, unknown>;
  onSubmit: (document: Record<string, unknown>) => void | Promise<void>;
  submitLabel?: string;
  disabled?: boolean;
  headerSlot?: ReactNode;
  documentClassFqn?: string;
};

export function SchemaPropertyGrid({
  fields,
  flattenedSchema,
  bundledSchema,
  lineage,
  registry,
  catalogResolver,
  initialDocument = {},
  onSubmit,
  submitLabel = "Save instance",
  disabled = false,
  headerSlot,
  documentClassFqn,
}: SchemaPropertyGridProps) {
  const rootSchema = useMemo(
    () =>
      isSchemaRecord(bundledSchema)
        ? bundledSchema
        : isSchemaRecord(flattenedSchema)
          ? flattenedSchema
          : { type: "object", properties: {} },
    [bundledSchema, flattenedSchema],
  );

  const declaringClassAncestryByField = useMemo(() => {
    if (!lineage?.length || !documentClassFqn) return undefined;
    const ancestry = lineage
      .filter((n) => n.lineageRole === "ancestor" || n.lineageRole === "self")
      .sort((a, b) => b.depth - a.depth)
      .map((n) => n.className);
    return Object.fromEntries(fields.map((f) => [f.fieldName, ancestry]));
  }, [fields, lineage, documentClassFqn]);

  return (
    <SchemaPropertyGridSurface
      fields={fields}
      schema={flattenedSchema}
      rootSchema={rootSchema}
      bundledSchema={bundledSchema}
      registry={registry}
      catalogResolver={catalogResolver}
      documentClassFqn={documentClassFqn}
      declaringClassAncestryByField={declaringClassAncestryByField}
      initialDocument={initialDocument}
      onSubmit={onSubmit}
      submitLabel={submitLabel}
      disabled={disabled}
      headerSlot={headerSlot}
      depth={0}
    />
  );
}
