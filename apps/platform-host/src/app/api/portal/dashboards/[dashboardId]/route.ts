import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionDeleteOperatorDashboard,
  portalSessionGetOperatorDashboard,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

type RouteContext = { params: Promise<{ dashboardId: string }> };

export async function GET(_request: Request, context: RouteContext) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { dashboardId } = await context.params;
    const token = await readSessionTokenOrThrow();
    const dashboard = await portalSessionGetOperatorDashboard(token, Number(dashboardId));
    const response = NextResponse.json({ dashboard });
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
    const { dashboardId } = await context.params;
    const token = await readSessionTokenOrThrow();
    const deleted = await portalSessionDeleteOperatorDashboard(token, Number(dashboardId));
    const response = NextResponse.json({ deleted });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
