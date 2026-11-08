import { NextResponse } from "next/server";
import { headers } from "next/headers";
import { getAuthProvider } from "@/server/auth/registry";
import { exchangeOidcCallback } from "@/server/auth/oidc";
import {
  clearOidcTransactionCookie,
  parseOidcTransactionCookie,
} from "@/server/auth/state-cookie";
import {
  isPortalBridgeConfigured,
  portalSessionOpenForScopeIdentity,
  PortalSessionDeniedError,
} from "@/server/portal/bridge";
import { buildSessionSetCookie } from "@/server/session/cookies";

export async function GET(
  request: Request,
  context: { params: Promise<{ providerId: string }> },
) {
  const { providerId } = await context.params;
  const cfg = getAuthProvider(providerId);
  if (!cfg || cfg.method !== "oidc_authorization_code") {
    return NextResponse.json({ error: "provider not found" }, { status: 404 });
  }
  if (!isPortalBridgeConfigured()) {
    return NextResponse.json({ error: "portal bridge is not configured" }, { status: 503 });
  }

  const hdrs = await headers();
  const tx = parseOidcTransactionCookie(hdrs.get("cookie"));
  if (!tx || tx.providerId !== providerId) {
    return NextResponse.json({ error: "invalid or expired login transaction" }, { status: 401 });
  }

  const url = new URL(request.url);
  const stateParam = url.searchParams.get("state");
  if (!stateParam || stateParam !== tx.state) {
    return NextResponse.json({ error: "state mismatch" }, { status: 401 });
  }

  try {
    const { issuer, subject, snapshot } = await exchangeOidcCallback(
      cfg,
      url,
      tx.state,
      tx.nonce,
      tx.codeVerifier,
    );
    const opened = await portalSessionOpenForScopeIdentity(cfg.scopeId, issuer, subject, snapshot);
    const response = NextResponse.redirect(new URL("/app", url.origin));
    response.headers.append("Set-Cookie", buildSessionSetCookie(opened.sessionToken));
    response.headers.append("Set-Cookie", clearOidcTransactionCookie());
    return response;
  } catch (err) {
    if (err instanceof PortalSessionDeniedError) {
      return NextResponse.redirect(new URL("/login?error=not_linked", url.origin));
    }
    return NextResponse.redirect(new URL("/login?error=oauth", url.origin));
  }
}
