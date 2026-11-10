import { NextResponse } from "next/server";
import {
  isPortalBridgeConfigured,
  portalSessionSecurity,
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
    const body = (await request.json()) as Record<string, unknown>;
    const action = String(body.action ?? "");
    const result = await portalSessionSecurity(token, action, body);
    const response = NextResponse.json(result);
    return withSessionCookie(response, token);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
