import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { isPortalBridgeConfigured, portalSessionRevoke } from "@/server/portal/bridge";
import { buildSessionClearCookie, SESSION_COOKIE_NAME } from "@/server/session/cookies";
export async function POST() {
  const response = NextResponse.json({ ok: true });
  response.headers.append("Set-Cookie", buildSessionClearCookie());

  if (!isPortalBridgeConfigured()) {
    return response;
  }

  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (token) {
    try {
      await portalSessionRevoke(token);
    } catch {
      // still clear client cookie
    }
  }
  return response;
}
