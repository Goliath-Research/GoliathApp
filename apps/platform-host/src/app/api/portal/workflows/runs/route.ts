import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionListRecentInstances,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";
import { resolveWorkflowRunsLimit, resolveWorkflowRunsRange } from "@/lib/workflow-runs-range";

export const dynamic = "force-dynamic";

/** GET /api/portal/workflows/runs?range=24h|7d|30d|all&limit=N */
export async function GET(request: Request) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const token = await readSessionTokenOrThrow();
    const url = new URL(request.url);
    const range = resolveWorkflowRunsRange(url.searchParams.get("range"));
    const limit = resolveWorkflowRunsLimit(url.searchParams.get("limit"));
    const rows = await portalSessionListRecentInstances(token, range.hoursBack, limit);
    const response = NextResponse.json({ range: range.key, limit, rows });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
