import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionGetDataType,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export async function GET(
  request: Request,
  context: { params: Promise<{ typeName: string }> },
) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const { typeName } = await context.params;
    const url = new URL(request.url);
    const version = url.searchParams.get("version");
    const token = await readSessionTokenOrThrow();
    const row = await portalSessionGetDataType(token, decodeURIComponent(typeName), version);
    const response = NextResponse.json({ type: row });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
