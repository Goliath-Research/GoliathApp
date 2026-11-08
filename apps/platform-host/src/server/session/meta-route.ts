import "server-only";

import { cookies } from "next/headers";
import { portalSessionTouch, PortalSessionDeniedError } from "../portal/bridge";
import { buildSessionSetCookie, SESSION_COOKIE_NAME } from "./cookies";
import { NextResponse } from "next/server";

export async function readSessionTokenOrThrow(): Promise<string> {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) {
    throw new PortalSessionDeniedError("missing session cookie");
  }
  const touched = await portalSessionTouch(token);
  if (!touched) {
    throw new PortalSessionDeniedError("session expired");
  }
  return token;
}

export function withSessionCookie(response: NextResponse, token: string): NextResponse {
  response.headers.append("Set-Cookie", buildSessionSetCookie(token));
  return response;
}
