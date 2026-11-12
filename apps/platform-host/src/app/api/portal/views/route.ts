import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionListOperatorViews,
  portalSessionUpsertOperatorView,
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
    const views = await portalSessionListOperatorViews(token);
    const response = NextResponse.json({ views });
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
    const viewId = await portalSessionUpsertOperatorView(token, {
      viewId: body.viewId == null ? undefined : Number(body.viewId),
      title: String(body.title ?? ""),
      description: body.description == null ? undefined : String(body.description),
      semanticRequestCode:
        body.semanticRequestCode == null ? null : String(body.semanticRequestCode),
      semanticRequestVersion:
        body.semanticRequestVersion == null ? undefined : String(body.semanticRequestVersion),
      metaClassName: body.metaClassName == null ? null : String(body.metaClassName),
      paramsJson:
        typeof body.paramsJson === "object" && body.paramsJson !== null
          ? (body.paramsJson as Record<string, unknown>)
          : {},
      visibility: body.visibility == null ? undefined : String(body.visibility),
    });
    const response = NextResponse.json({ viewId }, { status: body.viewId ? 200 : 201 });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
