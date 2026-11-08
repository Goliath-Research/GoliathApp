# Platform host — authentication methods (P1 extension)

Stacked on [platform-host-p1-auth.md](platform-host-p1-auth.md). The **App owns** provider registration, external identity resolution, and `portal.sp_session_open` — children add **metadata only** via `ChildAuthProviderRegistration` (see `packages/client/src/auth.ts`).

## Supported today (tested)

| Method | Protocol | Status | Evidence |
|--------|----------|--------|----------|
| **OIDC authorization code** | OAuth2/OIDC + PKCE | **Implemented** | `openid-client`, state/nonce cookies, `portal.sp_session_open_for_scope_identity` |
| Password | — | Planned | — |
| Passkey / WebAuthn | — | Planned | — |
| Email magic link | — | Planned | — |
| **Worker / gateway** | REST `POST /workers/session` | **Separate product surface** | Not the platform host |

## Identity rules (non-negotiable)

- Accounts resolve through **`RBAC.spresolveuserbyscopeidentity(scope, issuer, sub)`** — pre-linked `ExternalIdentities` only.
- **No** auto-link by unverified email alone.
- **Scope** required on session (`ActiveScopeID`); navigation remains scope-bound (see P1 nav SQL).

## Server configuration (secrets stay server-side)

| Variable | Purpose |
|----------|---------|
| `GOLIATH_AUTH_OIDC_PROVIDERS_JSON` | JSON array of OIDC provider configs (client secret server-only) |
| `GOLIATH_AUTH_STATE_SECRET` | HMAC for OIDC transaction cookie (≥ 16 chars) |
| `GOLIATH_PORTAL_*` | Portal DB bridge (same as P1 BFF) |

Example element (Entra/Google/generic OIDC share the same shape):

```json
[
  {
    "providerId": "entra_primary",
    "displayName": "Microsoft Entra ID",
    "issuer": "https://login.microsoftonline.com/{tenant}/v2.0",
    "clientId": "…",
    "clientSecret": "…",
    "scopeId": 123,
    "scopes": ["openid", "profile", "email"],
    "allowedOrigins": ["https://app.example.com"]
  }
]
```

`allowedOrigins` is **required** for each provider (no implicit allow-all from request headers). Origins are compared in canonical form (default ports normalized).

Public discovery: `GET /api/auth/providers` — no secrets, lists configured providers and method roadmap.

## Child extension

```typescript
import type { ChildAuthProviderRegistration } from "@goliath/client";

export const childAuthProviders: ChildAuthProviderRegistration[] = [
  {
    providerId: "entra_primary",
    displayName: "Contoso Entra",
    method: "oidc_authorization_code",
    iconKey: "identity:user",
    scopeId: 123,
  },
];
```

The host **does not** create a sign-in button unless the same `providerId` exists in `GOLIATH_AUTH_OIDC_PROVIDERS_JSON` (prevents stub/multi-label fake methods).

## Dev-establish

`POST /api/session/dev-establish` remains **integration-only** and is **not** a production sign-in path. OIDC is the production-capable human method in this PR.

## Tests

- `workflow_engine/tests/test_portal_session_identity.py` — linked identity, GS403 unlinked, wrong scope
- `apps/platform-host/src/server/auth/state-cookie.test.ts` — PKCE + signed transaction cookie
- Playwright — `/api/auth/providers` public metadata

Full OIDC callback against a live IdP requires operator-supplied registration (not performed in CI).
