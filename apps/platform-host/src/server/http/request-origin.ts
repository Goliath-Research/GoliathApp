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
