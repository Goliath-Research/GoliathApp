import type { PlatformAuthMethodKind } from "@goliath/client";

/** Server-held OIDC provider configuration (secrets never sent to the browser). */
export type OidcProviderConfig = {
  providerId: string;
  displayName: string;
  method: Extract<PlatformAuthMethodKind, "oidc_authorization_code">;
  issuer: string;
  clientId: string;
  clientSecret: string;
  scopeId: number;
  scopes: string[];
  /** Optional allowlist of redirect origins (defaults to host origin only). */
  allowedOrigins?: string[];
};

export type AuthProviderConfig = OidcProviderConfig;
