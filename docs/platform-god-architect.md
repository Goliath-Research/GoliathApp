# God Architect role

GoliathApp **dogfoods** its Meta model: the platform namespace (`platform/*`, inherited nav, and platform semantic catalog entries) is owned by the product, not by tenant `organization_admin` users. A single global role **`god_architect`** (display name **God Architect**) holds that authority.

## Role and permission

| Item | Value |
|------|--------|
| RBAC role | `god_architect` (`BypassScope` true) |
| Permission | `platform.model.architect` |
| Grant to David (user 1) | `GLOBAL` (non-scoped), idempotent via `portal.sp_security_meta_grant_god_architect_to_user(1)` |
| Meta catalog | `platform/Role` object + `platform/Permission` object after security Meta migration |

`organization_admin` keeps **`platform.model.author`** for **child / product** classes (namespaces your app owns). It does **not** authorize edits to GoliathApp platform class definitions, platform NavTree nodes, platform roles/permissions, platform semantic entities, or identity provider catalog objects.

## Session behavior

Sessions remain **single active role**. David (or any grantee) must **select God Architect** at sign-in to run platform model authoring APIs. Scoped org-admin work (users, role grants in the active organization, invitations) still uses the **organization_admin** active role.

## Enforcement

- **Class-level security**: `MetaClassRoleAccess` denies `organization_admin` create/update/delete on platform catalog classes; allows `god_architect`.
- **Security instance data** (`platform/User`, `platform/RoleGrant`, `platform/Invitation`, `platform/ExternalIdentity`, `platform/Organization`) stays under **`platform.security.admin`** and org-scoped admin UIs — ordinary object data, not schema authoring.
- **Session writes**: `sp_session_meta_class_create`, field upsert on `platform/*`, `sp_session_nav_register_node`, platform-namespace semantic registration, and granting `god_architect` require an active God Architect role + `platform.model.architect`.
- **Grants of God Architect**: only God Architect may assign or revoke; revokes cannot remove the **last** active global grant (enforced in session revoke paths).
- **Audit**: `portal.god_architect_audit` records platform catalog mutations and god_architect grant changes.

## Production verification

`portal.sp_security_meta_verify_production()` (and `workflow_engine/scripts/verify_security_meta_migration.sh`) includes:

| Check | Expectation |
|-------|-------------|
| `god_architect_role_seeded` | Role exists |
| `david_god_architect_global` | User 1 has active global god_architect in `mv_security_effective_grants` |
| `meta_user_ids_preserved` | Users `1` and `2` have `security_meta_legacy_map` entries pointing at `platform/User` rows whose `LegacyUserId` matches (Meta obj id may differ) |

## Child applications

Subclass and extend **your** product classes and semantic namespaces. The **`platform/*`** tree and GoliathApp seeds remain **god_architect-only**; child apps never receive platform schema write access through `organization_admin`.

## Related docs

- [Platform security Meta](platform-security-meta.md) — security object migration and PR stack
- [Platform generic Meta](platform-generic-meta.md) — generic class/object editors
- [Database population](database-population.md) — official seeds including NavTree
