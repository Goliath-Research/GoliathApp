# Platform host — P1 partial foundation (session BFF)

**P1 is not complete authentication.** Production OIDC / external identity → `portal.sp_session_open` is still pending. This milestone delivers a **session transport and permission-bound navigation foundation** only.

P1 adds a **same-origin BFF** in `apps/platform-host` that calls real PostgreSQL contracts:

- `portal.fn_session_resolve` / `portal.sp_session_touch` / `portal.sp_session_revoke`
- `portal.sp_session_open` (integration bootstrap only — not a production OIDC substitute)
- `portal.sp_session_operator_nav_tree` (permission-filtered NavTree; SQL in `portal_session_nav_api.sql`)

Session tokens are stored in an **httpOnly** cookie. The browser never receives DSNs, passwords, or raw session tokens in JavaScript.

PR **#58** remains the P0 host-only review unit. P1 lands on branch `cursor/platform-ui-p1-auth-3b72`, stacked on that host branch.

## Environment (server only)

| Variable | Required | Purpose |
|----------|----------|---------|
| `GOLIATH_PORTAL_DB` | Either this **or** host/user/password tuple | libpq URL for role `goliath_portal` |
| `POSTGRES_HOST` / `PGHOST` | If no `GOLIATH_PORTAL_DB` | Database host |
| `POSTGRES_DB` / `PGDATABASE` | If no `GOLIATH_PORTAL_DB` | Database name |
| `GOLIATH_PORTAL_PASSWORD` | If no `GOLIATH_PORTAL_DB` | Portal role password |
| `GOLIATH_PLATFORM_SESSION_COOKIE` | No | Cookie name (default `goliath_platform_session`) |

When bridge env vars are **missing**, session routes return **503** and fixture routes stay public — fail closed, not anonymous privileged access.

### Scope enforcement (navigation)

`portal.sp_session_operator_nav_tree` matches `Role2Node` rows **only** when `Sessions.ActiveScopeID = Role2Node.ScopeId`. Sessions without `ActiveScopeID` return **no** nav rows (fail closed — avoids treating NULL scope as “all tenants”).

### Integration-only dev login (disabled by default; never in `NODE_ENV=production`)

| Variable | Purpose |
|----------|---------|
| `GOLIATH_PLATFORM_HOST_DEV_LOGIN=1` | Enable `POST /api/session/dev-establish` |
| `GOLIATH_P1_DEV_LOGIN_USER_ID` | `RBAC.Users.ID` to pass to `portal.sp_session_open` |
| `GOLIATH_PLATFORM_HOST_DEV_LOGIN_SECRET` | Required header `X-Goliath-Dev-Login-Secret` |

This is for **CI/integration** with a disposable Postgres — not a production login UI.

## HTTP surface (host-owned)

| Route | Auth | Behavior |
|-------|------|----------|
| `/fixture` | Public | P0 fixture data only |
| `/app` | Server session | Redirects when unauthenticated / misconfigured |
| `GET /api/session/me` | Cookie | Session snapshot or 401 |
| `POST /api/session/logout` | Cookie | Revoke + clear cookie |
| `GET /api/navigation` | Cookie | Nav rows from `sp_session_operator_nav_tree` or 401 |
| `POST /api/session/dev-establish` | Secret header | Optional integration bootstrap |

## Client packages

- `@goliath/client` — `createPlatformBffClient()` (same-origin `fetch`, credentials included)
- `@goliath/platform-ui` — `OperatorNavList` with icon/kind fallback

Children extend `ChildHostExtension` (`packages/client/src/child-host.ts`).

## Pending (not P1)

- **Production OIDC** → external identity → `portal.sp_session_open` with provider snapshot (see `portal_session_api.sql`)
- **P2** Meta / schema editors
- **P3** Workflow designer & monitor
- **Azure / app.goliathresearch.com deploy** — blocked operationally; artifact path unchanged from [platform-host.md](platform-host.md)

## Design note: navigation roles

`portal.sp_session_operator_nav_tree` unions `portal.UserRoles`, scoped `RBAC.UserRoleGrants`, and `RBAC.usp_session_get_effective_roles_v2` before applying `Role2Node` visibility — so organization admins with scoped grants see nodes without relying on legacy `portal.UserRoles` alone.
