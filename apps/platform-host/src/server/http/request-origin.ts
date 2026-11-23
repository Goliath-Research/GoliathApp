/**
 * Origin claimed by the request (X-Forwarded-Host or Host, X-Forwarded-Proto).
 * Client-controlled: use only for comparison against an allowlist, never as a
 * redirect or link target. Use `allowlistedRequestOrigin` for those.
 */
export function requestOrigin(
  requestUrl: string,
  getHeader: (name: string) => string | null,
): string {
  const forwardedHost = getHeader("x-forwarded-host");
  const hostHeader = forwardedHost ?? getHeader("host");
  if (hostHeader) {
    const host = hostHeader.split(",")[0]?.trim();
    const forwardedProto = getHeader("x-forwarded-proto");
    const proto =
      forwardedProto?.split(",")[0]?.trim() ??
      new URL(requestUrl).protocol.replace(":", "") ??
      "http";
    if (host) {
      return `${proto}://${host}`;
    }
  }
  return new URL(requestUrl).origin;
}

export function requestOriginFromRequest(request: Request): string {
  return requestOrigin(request.url, (name) => request.headers.get(name));
}

/** Normalize origins for allowlist comparison (default ports, casing). */
export function canonicalizeOrigin(origin: string): string {
  try {
    return new URL(origin).origin;
  } catch {
    return origin;
  }
}

function httpOrigin(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return url.origin;
  } catch {
    return null;
  }
}

export function isOriginAllowlisted(origin: string, allowedOrigins: readonly string[]): boolean {
  const canonical = httpOrigin(origin);
  if (!canonical) return false;
  return allowedOrigins.some((entry) => httpOrigin(entry) === canonical);
}

/**
 * Public origin for redirects and links behind TLS-terminating proxies.
 * Headers are read once. The claimed origin is returned only when it is on
 * `allowedOrigins`; otherwise the first allowlisted origin, or the request URL
 * origin when nothing is allowlisted.
 */
export function allowlistedRequestOrigin(
  requestUrl: string,
  getHeader: (name: string) => string | null,
  allowedOrigins: readonly string[],
): string {
  const claimed = httpOrigin(requestOrigin(requestUrl, getHeader));
  if (claimed && isOriginAllowlisted(claimed, allowedOrigins)) {
    return claimed;
  }
  for (const entry of allowedOrigins) {
    const configured = httpOrigin(entry);
    if (configured) return configured;
  }
  return new URL(requestUrl).origin;
}

export function allowlistedOriginFromRequest(
  request: Request,
  allowedOrigins: readonly string[],
): string {
  return allowlistedRequestOrigin(request.url, (name) => request.headers.get(name), allowedOrigins);
}

export function allowlistedOriginFromHeaderStore(
  getHeader: (name: string) => string | null,
  allowedOrigins: readonly string[],
  fallbackUrl = "http://localhost",
): string {
  return allowlistedRequestOrigin(fallbackUrl, getHeader, allowedOrigins);
}

/** Canonical redirect_uri registered at authorization and used at token exchange. */
export function oidcRedirectUri(origin: string, providerId: string): string {
  return new URL(`/api/auth/oidc/${encodeURIComponent(providerId)}/callback`, origin).href;
}

/** OIDC token exchange must use the same public URL the IdP redirected to. */
export function oidcCallbackUrl(request: Request, origin: string, providerId: string): URL {
  const incoming = new URL(request.url);
  const url = new URL(oidcRedirectUri(origin, providerId));
  url.search = incoming.search;
  return url;
}
