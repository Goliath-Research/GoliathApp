import { redirect } from "next/navigation";
import { coercePresentationKind, type OperatorNavNode } from "@goliath/client";
import { OperatorPortalShell } from "@/components/OperatorPortalShell";
import {
  PortalBridgeMisconfiguredError,
  PortalSessionDeniedError,
  portalOperatorNavTree,
} from "@/server/portal/bridge";
import { requirePortalSession } from "@/server/session/require";
import { cookies } from "next/headers";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";

export const dynamic = "force-dynamic";

export default async function OperatorAppLayout({ children }: { children: React.ReactNode }) {
  try {
    const session = await requirePortalSession();
    const cookieStore = await cookies();
    const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
    if (!token) {
      redirect("/login");
    }
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
      <OperatorPortalShell session={session} nodes={nodes}>
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
