import { MetaInstanceWorkbench } from "@/components/MetaInstanceWorkbench";
import {
  portalSessionMetaClassFields,
  portalSessionMetaClassGet,
  portalSessionMetaClassLineage,
} from "@/server/portal/bridge";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";
import { cookies } from "next/headers";

/** The generic tree editor for one tree-shaped Meta class (NavTree uses portal/NavNode). */
export async function MetaTreePanel({ className }: { className: string }) {
  const token = (await cookies()).get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;
  let loaded;
  try {
    loaded = await Promise.all([
      portalSessionMetaClassGet(token, className),
      portalSessionMetaClassLineage(token, className),
      portalSessionMetaClassFields(token, className),
    ]);
  } catch (err) {
    return (
      <p role="alert">
        The {className} tree is not available to this role ({err instanceof Error ? err.message : "denied"}).
      </p>
    );
  }
  const [summary, lineage, fields] = loaded;
  return (
    <MetaInstanceWorkbench
      tree
      className={className}
      fields={fields}
      flattenedSchema={summary.schemaFlattenedJson}
      bundledSchema={summary.schemaBundledJson}
      lineage={lineage}
    />
  );
}
