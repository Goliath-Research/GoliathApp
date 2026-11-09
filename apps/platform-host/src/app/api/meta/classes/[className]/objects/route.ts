import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionMetaObjInsert,
  PortalForbiddenError,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export async function POST(
  request: Request,
  context: { params: Promise<{ className: string }> },
) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { className } = await context.params;
    const token = await readSessionTokenOrThrow();
    const body = (await request.json()) as { document?: unknown };
    const objId = await portalSessionMetaObjInsert(
      token,
      decodeURIComponent(className),
      body.document ?? {},
    );
    const response = NextResponse.json({ objId }, { status: 201 });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    if (err instanceof PortalForbiddenError) {
      return jsonError(403, err.message);
    }
    return mapPortalError(err);
  }
}
