import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import {
  isPortalBridgeConfigured,
  portalSessionResolve,
  portalSessionTouch,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { buildSessionSetCookie, SESSION_COOKIE_NAME } from "@/server/session/cookies";
import { jsonError, mapPortalError } from "@/server/http/errors";

export async function GET() {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const cookieStore = await cookies();
    const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
    if (!token) {
      return jsonError(401, "unauthenticated");
    }
    const session = await portalSessionResolve(token);
    if (!session) {
      return jsonError(401, "session denied");
    }
    const touched = await portalSessionTouch(token);
    if (!touched) {
      return jsonError(401, "session expired");
    }
    const response = NextResponse.json({
      sessionId: session.sessionId,
      userId: session.userId,
      email: session.email,
      fullName: session.fullName,
      activeScopeId: session.activeScopeId,
      activeRoleId: session.activeRoleId,
      activeRoleName: session.activeRoleName,
      expiresAtUtc: session.expiresAtUtc.toISOString(),
    });
    response.headers.append("Set-Cookie", buildSessionSetCookie(token));
    return response;
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
