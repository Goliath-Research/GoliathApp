/** Discriminates human sign-in transports from machine credentials (workers/gateway). */
export type PlatformAuthMethodKind = "oidc_authorization_code" | "password" | "passkey" | "email_magic_link";

/** Public discovery payload — no secrets. */
export type PublicAuthProvider = {
  providerId: string;
  displayName: string;
  method: PlatformAuthMethodKind;
  issuer: string;
  signInUrl: string;
  scopeId: number;
  presentationKind: "config" | "user";
};

/**
 * Child apps register additional providers at build time; the host merges configs server-side.
 * Children must not ship client secrets — only metadata and stable provider ids.
 */
export type ChildAuthProviderRegistration = {
  providerId: string;
  displayName: string;
  method: PlatformAuthMethodKind;
  /** Lucide allowlist key for sign-in button (via @goliath/ui). */
  iconKey?: string;
  /**
   * Scope id for RBAC.ScopeIdentityProviders binding — must match a platform-registered scope.
   * Host validates against DB allowlist before exposing the provider.
   */
  scopeId: number;
};
