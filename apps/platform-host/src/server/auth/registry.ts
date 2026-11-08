import type { PublicAuthProvider } from "@goliath/client";
import { PLATFORM_CHILD_AUTH_PROVIDERS } from "@/lib/child-auth-providers";
import type { AuthProviderConfig, OidcProviderConfig } from "./types";
export { assertRedirectOriginAllowed } from "./origin-allowlist";

function parseServerProviders(): OidcProviderConfig[] {
  const raw = process.env.GOLIATH_AUTH_OIDC_PROVIDERS_JSON?.trim();
  if (!raw) return [];
  const parsed = JSON.parse(raw) as unknown;
  if (!Array.isArray(parsed)) return [];
  const out: OidcProviderConfig[] = [];
  for (const row of parsed) {
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const providerId = String(r.providerId ?? "");
    const issuer = String(r.issuer ?? "");
    const clientId = String(r.clientId ?? "");
    const clientSecret = String(r.clientSecret ?? "");
    const scopeId = Number(r.scopeId);
    const allowedOrigins = Array.isArray(r.allowedOrigins) ? r.allowedOrigins.map(String) : [];
    if (
      !providerId ||
      !issuer ||
      !clientId ||
      !clientSecret ||
      !Number.isInteger(scopeId) ||
      scopeId <= 0 ||
      allowedOrigins.length === 0
    ) {
      continue;
    }
    out.push({
      providerId,
      displayName: String(r.displayName ?? providerId),
      method: "oidc_authorization_code",
      issuer,
      clientId,
      clientSecret,
      scopeId,
      scopes: Array.isArray(r.scopes) ? r.scopes.map(String) : ["openid", "profile", "email"],
      allowedOrigins,
    });
  }
  return out;
}

let cached: AuthProviderConfig[] | null = null;

export function listAuthProviderConfigs(): AuthProviderConfig[] {
  if (cached) return cached;
  const server = parseServerProviders();
  const childMeta = PLATFORM_CHILD_AUTH_PROVIDERS.filter((c) => c.method === "oidc_authorization_code");
  const byId = new Map(server.map((p) => [p.providerId, p]));
  for (const child of childMeta) {
    if (!byId.has(child.providerId)) {
      // Child ids without server config are not exposed (no stub sign-in buttons).
      continue;
    }
    const cfg = byId.get(child.providerId)!;
    byId.set(child.providerId, { ...cfg, displayName: child.displayName || cfg.displayName });
  }
  cached = [...byId.values()];
  return cached;
}

export function getAuthProvider(providerId: string): AuthProviderConfig | null {
  return listAuthProviderConfigs().find((p) => p.providerId === providerId) ?? null;
}

export function listPublicAuthProviders(origin: string): PublicAuthProvider[] {
  return listAuthProviderConfigs().map((p) => ({
    providerId: p.providerId,
    displayName: p.displayName,
    method: p.method,
    issuer: p.issuer,
    scopeId: p.scopeId,
    presentationKind: "config",
    signInUrl: `${origin}/api/auth/oidc/${encodeURIComponent(p.providerId)}/start`,
  }));
}

