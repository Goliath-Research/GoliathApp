import "server-only";

import { cookies } from "next/headers";
import {
  isPortalBridgeConfigured,
  portalSessionResolve,
  portalSessionTouch,
  PortalBridgeMisconfiguredError,
  PortalSessionDeniedError,
  type ResolvedPortalSession,
} from "../portal/bridge";
import { SESSION_COOKIE_NAME, sessionCookieStoreOptions } from "./cookies";

export async function requirePortalSession(): Promise<ResolvedPortalSession> {
  if (!isPortalBridgeConfigured()) {
    throw new PortalBridgeMisconfiguredError();
  }
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) {
    throw new PortalSessionDeniedError("missing session cookie");
  }
  const session = await portalSessionResolve(token);
  if (!session) {
    throw new PortalSessionDeniedError();
  }
  const touched = await portalSessionTouch(token);
  if (!touched) {
    throw new PortalSessionDeniedError("session expired");
  }
  cookieStore.set(SESSION_COOKIE_NAME, token, sessionCookieStoreOptions());
  return session;
}

export async function optionalPortalSession(): Promise<ResolvedPortalSession | null> {
  if (!isPortalBridgeConfigured()) return null;
  try {
    return await requirePortalSession();
  } catch {
    return null;
  }
}
