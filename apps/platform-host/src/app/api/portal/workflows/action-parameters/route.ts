import { NextResponse } from "next/server";
import { isPortalBridgeConfigured, portalSessionCall, PortalSessionDeniedError } from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export const dynamic = "force-dynamic";

/**
 * GET /api/portal/workflows/action-parameters?action=<action_name> — the action's typed parameters
 * (from its Meta class method) as a flat object schema for the node parameter grid.
 */
export async function GET(request: Request) {
  if (!isPortalBridgeConfigured()) return jsonError(503, "portal bridge is not configured");
  try {
    const token = await readSessionTokenOrThrow();
    const action = (new URL(request.url).searchParams.get("action") ?? "").trim();
    if (!action) return jsonError(400, "action is required");
    const rows = await portalSessionCall(
      token,
      "SELECT portal.sp_session_workflow_action_parameters($1, $2) AS schema",
      [action],
    );
    return withSessionCookie(NextResponse.json({ action, schema: rows[0]?.schema ?? null }), token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) return jsonError(401, err.message);
    return mapPortalError(err);
  }
}
