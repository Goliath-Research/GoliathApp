# Platform security as Meta objects

GoliathApp is moving **users, roles, permissions, grants, external identities, and invitations** from hand-maintained RBAC / Onboarding tables into the **Meta class hierarchy** (`Meta.Classes`, `Meta.Objs`, `Meta.ObjValues`, `Meta.Links`). Child applications subclass these platform classes; the operator portal edits them through **generic class/object editors and views**, not bespoke admin screens.

## Class list (platform namespace)

| FQN | Extends | Purpose |
|-----|---------|---------|
| `platform/User` | `platform/Person` | Portal operator; `Email`, `FullName`, `Active`, `LegacyUserId` (= `RBAC.Users.ID`; **not** necessarily equal to `Meta.Objs.ID`) |
| `platform/Role` | `platform/Entity` | Named role; `RoleName`, `BypassScope` |
| `platform/Permission` | `platform/Entity` | Permission name; `PermissionName` |
| `platform/RoleGrant` | `platform/Entity` | Grant linking user, role, organization scope; `Active`, `GrantedAtUtc`, `RevokedAtUtc`, `GrantType` |
| `platform/ExternalIdentity` | `platform/Entity` | OIDC subject link; `ProviderId`, `Subject`, `EmailSnapshot`, `Active` |
| `platform/Invitation` | `platform/Entity` | Pending invite; `Email`, `Status`, `ExpiresAtUtc`, `DefaultRoleId`, provider fields |
| `platform/Organization` | `platform/Party` | *(existing)* Organization / **scope** anchor for grants |

Instance links on `platform/RoleGrant`: `GrantUser` → `platform/User`, `GrantRole` → `platform/Role`, `GrantOrganization` → `platform/Organization`.  
`platform/ExternalIdentity` links `IdentityUser` → `platform/User`.  
`platform/Role` links `RolePermissions` → `platform/Permission` (many).

## Enforcement and performance

- **Authoritative data** lives in Meta after migration (`portal.sp_security_meta_migrate_from_legacy`, idempotent).
- **Fast path**: `portal.mv_security_effective_grants` (materialized view) refreshed by `portal.sp_security_meta_refresh_cache()` after migration and after security-class writes (Phase 2: trigger on `Meta.ObjValues` for security class IDs).
- **Session APIs** (`sp_session_set_active_role`, nav tree, invitations, first-sign-in linking) read the cache view via `portal.fn_security_user_grant_role_ids`, not `RBAC.UserRoleGrants` directly.
- **RBAC tables** remain during transition for rollback; new writes should go through Meta session APIs (stack PR 2). Drops are documented, not automated in v1.
- **Class-level security** on all security classes: only `platform.security.admin` may create/update/delete; users cannot mutate their own grants (enforced in session admin APIs + Meta gates).

## Production migration

1. Create a **Neon backup branch** (or full backup) of production.
2. Deploy application build that includes `platform_security_meta_*.sql` in `apply_schema.sh`.
3. Run `workflow_engine/sql_pg/apply_schema.sh` (no extra one-off SQL beyond the script).
4. Migration runs inside apply via `platform_security_meta_migrate.sql`.
5. Run verification:

```bash
workflow_engine/scripts/verify_security_meta_migration.sh
```

Expected for Goliath production (post-migration):

| Check | User 1 (David) | User 2 (Inty) |
|-------|----------------|---------------|
| `organization_admin` grant on scope 1 | yes | yes |
| Entra external identity for David | provider 1, subject preserved | n/a |
| `meta_user_ids_preserved` | `security_meta_legacy_map` → `platform/User` with `LegacyUserId` = RBAC user id | same |

`meta_user_ids_preserved` does **not** require `Meta.Objs.ID = RBAC.Users.ID`. Production may already have low `Meta.Objs` ids (for example NavNodes `1..47`); users `1` and `2` then become `platform/User` instances `48` and `49` as long as the legacy map and `LegacyUserId` match.

## Legacy table drop plan (post-PR C)

After one release with Meta-only enforcement verified on Neon backup + production smoke:

| Phase | Action |
|-------|--------|
| **D1** | Stop writing `RBAC.UserRoleGrants`, `ExternalIdentities`, `Onboarding.Invitations` (sync helpers removed) |
| **D2** | Drop read paths from session SQL; keep tables read-only for audit export |
| **D3** | Archive tables to `legacy_*` schema, then `DROP` when no downstream BI depends on them |

Tables targeted: `"RBAC"."UserRoleGrants"`, `"RBAC"."ExternalIdentities"`, `"RBAC"."Users"` (sessions retain numeric user id via `platform/User.LegacyUserId`), `"Onboarding"."Invitations"`.  
Retain: `"RBAC"."Sessions"`, `"RBAC"."SessionTokens"`, `"RBAC"."Session_Roles"`, `"RBAC"."IdentityProviders"`, `"RBAC"."ScopeIdentityProviders"` until OIDC catalog moves to Meta.

## God Architect (platform model authority)

GoliathApp-owned **`platform/*` schema and catalog** (class definitions, NavTree platform nodes, platform roles/permissions, platform semantic entries, identity provider catalog) is editable only by the global **`god_architect`** role and **`platform.model.architect`** permission. User **1** receives the global grant at apply time; production verify checks it. See [God Architect role](platform-god-architect.md).

## Stacked PR plan (recommended)

This direction is **too large for one safe merge**. Use three stacks:

| PR | Scope |
|----|--------|
| **A** (base) | Invitation fix, single active role per session, OIDC linking |
| **B** (this work) | Meta security classes, idempotent migration, materialized grant cache, resolver wired into session role selection + tests + verify script |
| **C** | Rewrite remaining RBAC readers (invitations, admin list, RBAC CRUD) to Meta; replace `AdminUsersWorkspace` with generic views; CI upgrade-path test; optional RBAC table deprecation |

Do **not merge** until B and C are reviewed with a Neon restore drill.

## Operator UI (target state, PR C)

- **Administration → Users** → saved view on `platform/User` with linked grants.
- **Administration → Roles** → view on `platform/Role`.
- Revoke grant → update `platform/RoleGrant.RevokedAtUtc` via object editor (session-gated).
- Role picker at sign-in unchanged (still `sp_session_set_active_role`).
