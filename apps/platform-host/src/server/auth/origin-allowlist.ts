import type { OidcProviderConfig } from "./types";
import { isOriginAllowlisted } from "../http/request-origin";

export function assertRedirectOriginAllowed(origin: string, cfg: OidcProviderConfig): void {
  const allowed = cfg.allowedOrigins;
  if (!allowed?.length) {
    throw new Error("allowedOrigins is required for OIDC providers");
  }
  if (!isOriginAllowlisted(origin, allowed)) {
    throw new Error("redirect origin is not allowlisted");
  }
}
