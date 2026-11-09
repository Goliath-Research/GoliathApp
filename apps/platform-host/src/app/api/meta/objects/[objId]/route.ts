import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionMetaObjGet,
  portalSessionMetaObjUpdate,
  PortalForbiddenError,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

function parseObjId(raw: string): number | null {
  const n = Number.parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ objId: string }> },
) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { objId: rawId } = await context.params;
    const objId = parseObjId(rawId);
    if (objId == null) {
      return jsonError(400, "invalid obj id");
    }
    const token = await readSessionTokenOrThrow();
    const row = await portalSessionMetaObjGet(token, objId);
    const response = NextResponse.json({ object: row });
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

export async function PATCH(
  request: Request,
  context: { params: Promise<{ objId: string }> },
) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { objId: rawId } = await context.params;
    const objId = parseObjId(rawId);
    if (objId == null) {
      return jsonError(400, "invalid obj id");
    }
    const token = await readSessionTokenOrThrow();
    const body = (await request.json()) as { document?: unknown };
    await portalSessionMetaObjUpdate(token, objId, body.document ?? {});
    const response = NextResponse.json({ ok: true });
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
