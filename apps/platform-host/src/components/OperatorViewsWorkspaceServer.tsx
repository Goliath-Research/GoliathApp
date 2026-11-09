import { cookies } from "next/headers";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";
import {
  portalSessionListOperatorViews,
  portalSessionMetaListClasses,
  portalSessionPlatformQuery,
} from "@/server/portal/bridge";
import { OperatorViewsWorkspace } from "@/components/OperatorViewsWorkspace";

export async function OperatorViewsWorkspaceServer({ runViewId }: { runViewId?: number }) {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) return null;

  const [views, catalogRows, classes] = await Promise.all([
    portalSessionListOperatorViews(token),
    portalSessionPlatformQuery(
      token,
      `SELECT request_code, display_name, namespace, entity_code
       FROM portal.sp_list_semantic_catalog($1)`,
    ),
    portalSessionMetaListClasses(token),
  ]);

  return (
    <OperatorViewsWorkspace
      catalog={catalogRows.map((row) => ({
        requestCode: String(row.request_code),
        displayName: String(row.display_name),
        namespace: String(row.namespace),
        entityCode: String(row.entity_code),
      }))}
      metaClasses={classes.map((c) => c.className)}
      initialViews={views.map((v) => ({
        viewId: v.viewId,
        title: v.title,
        description: v.description,
        semanticRequestCode: v.semanticRequestCode,
        metaClassName: v.metaClassName,
      }))}
      runViewId={runViewId}
    />
  );
}
