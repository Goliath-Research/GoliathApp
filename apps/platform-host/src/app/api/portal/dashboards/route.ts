import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionListOperatorDashboards,
  portalSessionUpsertOperatorDashboard,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export async function GET() {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const token = await readSessionTokenOrThrow();
    const dashboards = await portalSessionListOperatorDashboards(token);
    const response = NextResponse.json({ dashboards });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}

export async function POST(request: Request) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const token = await readSessionTokenOrThrow();
    const body = (await request.json()) as Record<string, unknown>;
    const dashboardId = await portalSessionUpsertOperatorDashboard(token, {
      dashboardId: body.dashboardId == null ? undefined : Number(body.dashboardId),
      title: String(body.title ?? ""),
      description: body.description == null ? undefined : String(body.description),
    });
    const response = NextResponse.json({ dashboardId }, { status: body.dashboardId ? 200 : 201 });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
