import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionDeleteOperatorView,
  portalSessionGetOperatorView,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

type RouteContext = { params: Promise<{ viewId: string }> };

export async function GET(_request: Request, context: RouteContext) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { viewId } = await context.params;
    const token = await readSessionTokenOrThrow();
    const view = await portalSessionGetOperatorView(token, Number(viewId));
    const response = NextResponse.json({ view });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}

export async function DELETE(_request: Request, context: RouteContext) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { viewId } = await context.params;
    const token = await readSessionTokenOrThrow();
    const deleted = await portalSessionDeleteOperatorView(token, Number(viewId));
    const response = NextResponse.json({ deleted });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
