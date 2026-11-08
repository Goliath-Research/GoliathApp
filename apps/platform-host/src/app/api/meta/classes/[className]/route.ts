import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionMetaClassGet,
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
    const summary = await portalSessionMetaClassGet(token, decodeURIComponent(className));
    const response = NextResponse.json({ class: summary });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
