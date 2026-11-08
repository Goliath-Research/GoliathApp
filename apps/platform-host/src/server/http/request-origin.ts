/**
 * Public origin for redirects and OIDC callback URLs behind TLS-terminating proxies.
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

export function requestOriginFromHeaderStore(
  getHeader: (name: string) => string | null,
  fallbackUrl = "http://localhost",
): string {
  return requestOrigin(fallbackUrl, getHeader);
}

/** Canonical redirect_uri registered at authorization and used at token exchange. */
export function oidcRedirectUri(origin: string, providerId: string): string {
  return new URL(`/api/auth/oidc/${encodeURIComponent(providerId)}/callback`, origin).href;
}

/** OIDC token exchange must use the same public URL the IdP redirected to. */
export function oidcCallbackUrl(request: Request, providerId: string): URL {
  const incoming = new URL(request.url);
  const url = new URL(oidcRedirectUri(requestOriginFromRequest(request), providerId));
  url.search = incoming.search;
  return url;
}
