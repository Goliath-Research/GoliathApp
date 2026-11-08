import type { OidcProviderConfig } from "./types";
import { canonicalizeOrigin } from "../http/request-origin";

export function assertRedirectOriginAllowed(origin: string, cfg: OidcProviderConfig): void {
  const allowed = cfg.allowedOrigins;
  if (!allowed?.length) {
    throw new Error("allowedOrigins is required for OIDC providers");
  }
  const canonical = canonicalizeOrigin(origin);
  const allowSet = new Set(allowed.map((entry) => canonicalizeOrigin(entry)));
  if (!allowSet.has(canonical)) {
    throw new Error("redirect origin is not allowlisted");
  }
}
