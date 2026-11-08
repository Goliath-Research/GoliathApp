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

export function requestOriginFromHeaderStore(
  getHeader: (name: string) => string | null,
  fallbackUrl = "http://localhost",
): string {
  return requestOrigin(fallbackUrl, getHeader);
}

/** OIDC token exchange must use the same public URL the IdP redirected to. */
export function oidcCallbackUrl(request: Request, providerId: string): URL {
  const origin = requestOriginFromRequest(request);
  const incoming = new URL(request.url);
  const path = `/api/auth/oidc/${encodeURIComponent(providerId)}/callback${incoming.search}`;
  return new URL(path, origin);
}
