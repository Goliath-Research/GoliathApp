import { redirect } from "next/navigation";
import { coercePresentationKind } from "@goliath/client";
import { OperatorNavList } from "@goliath/platform-ui";
import { requirePortalSession } from "@/server/session/require";
import { PortalBridgeMisconfiguredError, PortalSessionDeniedError, portalOperatorNavTree } from "@/server/portal/bridge";
import { cookies } from "next/headers";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";

export const dynamic = "force-dynamic";

export default async function AuthenticatedAppPage() {
  try {
    const session = await requirePortalSession();
    const cookieStore = await cookies();
    const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
    if (!token) {
      redirect("/?auth=required");
    }
    const rows = await portalOperatorNavTree(token);
    const nodes = rows.map((row) => ({
      nodeId: row.nodeId,
      parentId: row.parentId,
      caption: row.caption,
      seq: row.seq,
      presentationKind: coercePresentationKind(row.presentationKind),
    }));
    return (
      <div className="g-host-app">
        <p className="kicker">[Authenticated operator shell — P1]</p>
        <h2>Signed-in workspace</h2>
        <p className="g-host-home__lead">
          Navigation below is loaded from <code>portal.sp_session_operator_nav_tree</code> on the server.
          Hiding a link in the browser does not grant access — direct API calls without a session return 401.
        </p>
        <section aria-labelledby="operator-session-heading">
          <h3 id="operator-session-heading">Session</h3>
          <p>
            {session.fullName} · <code>{session.email}</code>
          </p>
        </section>
        <section aria-labelledby="operator-nav-heading">
          <h3 id="operator-nav-heading">Permission-filtered navigation</h3>
          <OperatorNavList nodes={nodes} />
        </section>
      </div>
    );
  } catch (err) {
    if (err instanceof PortalBridgeMisconfiguredError) {
      redirect("/?auth=unconfigured");
    }
    if (err instanceof PortalSessionDeniedError) {
      redirect("/?auth=required");
    }
    throw err;
  }
}
