import type { ChildAuthProviderRegistration } from "./auth.js";

/** Example child registration — copy into the child bundle; host merges at build time. */
export const EXAMPLE_CHILD_AUTH_PROVIDERS: ChildAuthProviderRegistration[] = [
  {
    providerId: "child_acme_entra",
    displayName: "Acme (Entra ID)",
    method: "oidc_authorization_code",
    iconKey: "identity:user",
    scopeId: 1,
  },
];
