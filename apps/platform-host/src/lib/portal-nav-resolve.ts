import { cookies } from "next/headers";
import { nodePathFromUrlPathname, resolvePortalWorkspace } from "@/lib/portal-node-registry";
import type { PortalWorkspaceSpec } from "@/lib/portal-node-registry";
import { portalOperatorNavTree } from "@/server/portal/bridge";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";

export async function resolveWorkspaceForPathname(pathname: string): Promise<{
  spec: PortalWorkspaceSpec;
  metaClassOverride?: string;
}> {
  const nodePath = nodePathFromUrlPathname(pathname);
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (token) {
    try {
      const rows = await portalOperatorNavTree(token);
      const row = rows.find((r) => r.nodePath === nodePath);
      if (row) {
        const spec = resolvePortalWorkspace(nodePath, {
          presentationKind: row.presentationKind,
          infoName: row.navInfoName,
        });
        return {
          spec,
          metaClassOverride: spec.metaClass,
        };
      }
    } catch {
      /* fall through to path-only resolver */
    }
  }
  const spec = resolvePortalWorkspace(nodePath);
  return { spec, metaClassOverride: spec.metaClass };
}
