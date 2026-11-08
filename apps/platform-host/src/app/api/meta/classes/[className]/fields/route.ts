import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionMetaClassFields,
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
    const fields = await portalSessionMetaClassFields(token, decodeURIComponent(className));
    const response = NextResponse.json({ fields });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
