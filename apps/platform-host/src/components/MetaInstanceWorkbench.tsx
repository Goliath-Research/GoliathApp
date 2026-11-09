"use client";

import type { MetaClassField, MetaClassLineageNode } from "@goliath/client";
import { createPlatformBffClient } from "@goliath/client";
import { SchemaPropertyGrid } from "@goliath/platform-ui";
import { useMemo, useState } from "react";
import { EXAMPLE_CHILD_EXTENSION } from "@/lib/child-extension";
import { hierarchyRegistryFromManifest } from "@/lib/hierarchy-registry";
import {
  createHostMetaCatalogResolver,
  type MetaCatalogClassFixture,
} from "@/lib/meta-catalog-resolver";
import { MetaJsonDocumentEditor } from "./MetaJsonDocumentEditor";

export type MetaInstanceWorkbenchProps = {
  className: string;
  fields: MetaClassField[];
  flattenedSchema: unknown;
  bundledSchema?: unknown;
  lineage?: MetaClassLineageNode[];
  catalogClassFixtures?: Record<string, MetaCatalogClassFixture>;
};

export function MetaInstanceWorkbench({
  className,
  fields,
  flattenedSchema,
  bundledSchema,
  lineage,
  catalogClassFixtures,
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
  const [lastObjId, setLastObjId] = useState<number | null>(null);
  const [roundtrip, setRoundtrip] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  async function save(document: Record<string, unknown>) {
    setStatus(null);
    setRoundtrip(null);
    if (lastObjId != null) {
      await client.updateMetaObject(lastObjId, document);
      const row = await client.getMetaObject(lastObjId);
      setRoundtrip(JSON.stringify(row.document, null, 2));
      setStatus(`Updated object #${lastObjId} — server merge round-trip below.`);
      return;
    }
    const { objId } = await client.createMetaObject(className, document);
    setLastObjId(objId);
    const row = await client.getMetaObject(objId);
    setRoundtrip(JSON.stringify(row.document, null, 2));
    setStatus(`Created object #${objId} — server merge round-trip below.`);
  }

  return (
    <div className="g-meta-workbench">
      <SchemaPropertyGrid
        fields={fields}
        flattenedSchema={flattenedSchema}
        bundledSchema={bundledSchema}
        lineage={lineage}
        registry={registry}
        catalogResolver={catalogResolver}
        documentClassFqn={className}
        onSubmit={save}
        submitLabel={
          lastObjId != null
            ? "Update via BFF (portal.sp_session_meta_obj_update)"
            : "Create via BFF (server Meta.sp_obj_*)"
        }
      />
      {status ? <p role="status">{status}</p> : null}
      {lastObjId != null && roundtrip ? (
        <details open>
          <summary>Merged document from portal.sp_session_meta_obj_get</summary>
          <pre className="g-host-code-block">{roundtrip}</pre>
        </details>
      ) : null}
      <MetaJsonDocumentEditor flattenedSchema={flattenedSchema} />
    </div>
  );
}
