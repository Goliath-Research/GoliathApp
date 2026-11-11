import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import {
  isPortalBridgeConfigured,
  portalSetActiveRole,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { SESSION_COOKIE_NAME } from "@/server/session/cookies";
import { jsonError, mapPortalError } from "@/server/http/errors";

export async function POST(request: Request) {
  if (!isPortalBridgeConfigured()) {
    return jsonError(503, "portal bridge is not configured");
  }
  try {
    const cookieStore = await cookies();
    const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
    if (!token) {
      return jsonError(401, "unauthenticated");
    }
    const body = (await request.json()) as { roleId?: unknown };
    const roleId = Number(body.roleId);
    if (!Number.isFinite(roleId) || roleId <= 0) {
      return jsonError(400, "roleId is required");
    }
    const selected = await portalSetActiveRole(token, roleId);
    return NextResponse.json(selected);
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return jsonError(401, err.message);
    }
    return mapPortalError(err);
  }
}
