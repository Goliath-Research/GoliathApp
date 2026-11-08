import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionMetaClassLineage,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export async function GET(
  _request: Request,
  context: { params: Promise<{ className: string }> },
) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { className } = await context.params;
    const token = await readSessionTokenOrThrow();
    const lineage = await portalSessionMetaClassLineage(token, decodeURIComponent(className));
    const response = NextResponse.json({ lineage });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
