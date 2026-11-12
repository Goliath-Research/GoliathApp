import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionListDashboardWidgets,
  portalSessionSetDashboardWidgets,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export async function GET(
  _request: Request,
  context: { params: Promise<{ dashboardId: string }> },
) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { dashboardId } = await context.params;
    const token = await readSessionTokenOrThrow();
    const widgets = await portalSessionListDashboardWidgets(token, Number(dashboardId));
    const response = NextResponse.json({ widgets });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}

export async function POST(
  request: Request,
  context: { params: Promise<{ dashboardId: string }> },
) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { dashboardId } = await context.params;
    const token = await readSessionTokenOrThrow();
    const body = (await request.json()) as { widgets?: Array<Record<string, unknown>> };
    const widgets = (body.widgets ?? []).map((w, idx) => ({
      viewId: Number(w.viewId),
      sortOrder: w.sortOrder == null ? (idx + 1) * 10 : Number(w.sortOrder),
      columnSpan: w.columnSpan == null ? 1 : Number(w.columnSpan),
      gridX: w.gridX == null ? 0 : Number(w.gridX),
      gridY: w.gridY == null ? 0 : Number(w.gridY),
      gridW: w.gridW == null ? 4 : Number(w.gridW),
      gridH: w.gridH == null ? 2 : Number(w.gridH),
      widgetTitle: w.widgetTitle == null ? "" : String(w.widgetTitle),
      vizOverride:
        typeof w.vizOverride === "object" && w.vizOverride !== null
          ? (w.vizOverride as Record<string, unknown>)
          : {},
    }));
    const count = await portalSessionSetDashboardWidgets(token, Number(dashboardId), widgets);
    const response = NextResponse.json({ widgetCount: count });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
