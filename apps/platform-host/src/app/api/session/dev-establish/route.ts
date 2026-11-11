import { NextResponse } from "next/server";
import {
  devLoginAllowed,
  devLoginSecret,
  resolveDevEstablishUserId,
} from "@/server/portal/env";
import {
  isPortalBridgeConfigured,
  portalAutoSelectActiveRole,
  portalSessionOpen,
} from "@/server/portal/bridge";
import { buildSessionSetCookie } from "@/server/session/cookies";
import { jsonError } from "@/server/http/errors";

/**
 * Integration-only session minting. Disabled unless GOLIATH_PLATFORM_HOST_DEV_LOGIN=1.
 * Requires header X-Goliath-Dev-Login-Secret matching GOLIATH_PLATFORM_HOST_DEV_LOGIN_SECRET.
 * Production OIDC → portal.sp_session_open belongs in a future auth provider bridge.
 */
export async function POST(request: Request) {
  if (!devLoginAllowed()) {
    return jsonError(404, "not available");
  }
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  const secret = devLoginSecret();
  if (secret == null) {
    return jsonError(503, "dev login is misconfigured");
  }
  const provided = request.headers.get("x-goliath-dev-login-secret");
  if (!provided || provided !== secret) {
    return jsonError(403, "dev login denied");
  }

  const userResolution = resolveDevEstablishUserId(request.headers.get("x-goliath-dev-login-user-id"));
  if (!userResolution.ok) {
    return jsonError(userResolution.status, userResolution.message);
  }
  const userId = userResolution.userId;

  const scopeHeader = request.headers.get("x-goliath-dev-login-scope-id");
  const activeScopeId =
    scopeHeader && Number.isInteger(Number(scopeHeader)) ? Number(scopeHeader) : null;

  const opened = await portalSessionOpen(userId, activeScopeId);
  if (activeScopeId != null) {
    await portalAutoSelectActiveRole(opened.sessionToken);
  }
  const response = NextResponse.json({
    ok: true,
    expiresAtUtc: opened.expiresAtUtc.toISOString(),
  });
  response.headers.append("Set-Cookie", buildSessionSetCookie(opened.sessionToken));
  return response;
}
