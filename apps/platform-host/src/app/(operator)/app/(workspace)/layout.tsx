import { redirect } from "next/navigation";
import { coercePresentationKind, type OperatorNavNode } from "@goliath/client";
import { OperatorPortalShell } from "@/components/OperatorPortalShell";
import { shouldRedirectToNoRole, shouldRedirectToRoleSelection } from "@/lib/session-active-role";
import {
  PortalBridgeMisconfiguredError,
  PortalSessionDeniedError,
  portalActiveRoleState,
  portalAutoSelectActiveRole,
  portalOperatorNavTree,
  portalSessionResolve,
} from "@/server/portal/bridge";
import { getRequestProductDefinition } from "@/server/product/request-product";
import { requirePortalSession } from "@/server/session/require";
import { cookies } from "next/headers";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";

export const dynamic = "force-dynamic";

export default async function OperatorWorkspaceLayout({ children }: { children: React.ReactNode }) {
  try {
    const session = await requirePortalSession();
    const cookieStore = await cookies();
    const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
    if (!token) {
      redirect("/login");
    }

    await portalAutoSelectActiveRole(token);
    const resolved = (await portalSessionResolve(token)) ?? session;
    const roleState = await portalActiveRoleState(token);

    if (shouldRedirectToNoRole(roleState)) {
      redirect("/app/onboarding/no-role");
    }
    if (shouldRedirectToRoleSelection(roleState)) {
      redirect("/app/onboarding/select-role");
    }

    const product = await getRequestProductDefinition();
    const rows = await portalOperatorNavTree(token);
    const nodes: OperatorNavNode[] = rows.map((row) => ({
      nodeId: row.nodeId,
      parentId: row.parentId,
      caption: row.caption,
      seq: row.seq,
      presentationKind: coercePresentationKind(row.presentationKind),
      nodePath: row.nodePath,
    }));

    return (
      <OperatorPortalShell
        session={resolved}
        nodes={nodes}
        brandName={product.displayName}
        brandSubtitle={product.portalSubtitle}
      >
        {children}
      </OperatorPortalShell>
    );
  } catch (err) {
    if (err instanceof PortalBridgeMisconfiguredError) {
      redirect("/?auth=unconfigured");
    }
    if (err instanceof PortalSessionDeniedError) {
      redirect("/login");
    }
    throw err;
  }
}
