import { NextResponse } from "next/server";
import {
  assertRedirectOriginAllowed,
  getAuthProvider,
} from "@/server/auth/registry";
import { buildOidcAuthorizationUrl } from "@/server/auth/oidc";
import {
  buildOidcTransactionCookie,
  createOidcTransaction,
  isAuthStateSigningConfigured,
} from "@/server/auth/state-cookie";
import { requestOriginFromRequest } from "@/server/http/request-origin";

export async function GET(
  request: Request,
  context: { params: Promise<{ providerId: string }> },
) {
  const { providerId } = await context.params;
  const cfg = getAuthProvider(providerId);
  if (!cfg || cfg.method !== "oidc_authorization_code") {
    return NextResponse.json({ error: "provider not found" }, { status: 404 });
  }
  if (!isAuthStateSigningConfigured()) {
    return NextResponse.json({ error: "auth is not configured" }, { status: 503 });
  }

  const origin = requestOriginFromRequest(request);
  try {
    assertRedirectOriginAllowed(origin, cfg);
  } catch {
    return NextResponse.json({ error: "origin not allowed" }, { status: 403 });
  }

  const tx = createOidcTransaction({ providerId: cfg.providerId, scopeId: cfg.scopeId });
  const redirectUri = `${origin}/api/auth/oidc/${encodeURIComponent(cfg.providerId)}/callback`;
  const authUrl = await buildOidcAuthorizationUrl(
    cfg,
    redirectUri,
    tx.state,
    tx.nonce,
    tx.codeVerifier,
  );
  const response = NextResponse.redirect(authUrl);
  response.headers.append("Set-Cookie", buildOidcTransactionCookie(tx));
  return response;
}
