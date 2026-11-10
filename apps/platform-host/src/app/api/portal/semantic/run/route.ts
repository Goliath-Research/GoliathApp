import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionRunSemanticRequest,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { jsonError, mapPortalError } from "@/server/http/errors";
import { readSessionTokenOrThrow, withSessionCookie } from "@/server/session/meta-route";

export async function POST(request: Request) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const token = await readSessionTokenOrThrow();
    const body = (await request.json()) as { requestCode?: string; params?: Record<string, unknown>; version?: string };
    const requestCode = String(body.requestCode ?? "");
    if (!requestCode) {
      return jsonError(400, "requestCode is required");
    }
    const rows = await portalSessionRunSemanticRequest(
      token,
      requestCode,
      body.params ?? {},
      body.version ?? "1",
    );
    const response = NextResponse.json({ rows });
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
