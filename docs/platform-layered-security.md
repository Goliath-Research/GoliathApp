# Platform layered security

GoliathApp combines **global role permissions**, **class-level Meta grants**, and **per-object ACLs** so child applications inherit a uniform model.

## Resolution order

1. **Object deny** for the user or any effective role → **denied**
2. **Object allow** for the user or any effective role → **allowed** (for that action)
3. **Class rule** per role: walk from the concrete class up ancestors; the **most specific** rule for each role wins (`allow` / `deny` / inherit global)
4. **Global** `RBAC.Role_Permissions` (for example `meta.object.read`) when no class rule applies for that role

A user is allowed when **any** scoped role succeeds. **Deny** on a class applies to that class and subclasses until a more specific subclass rule overrides it.

## Administration

Operators with `platform.security.admin` and NavTree entitlements use:

- `/app/admin/users` — users, invitations, scoped role grants (roles column + per-grant revoke in active scope)

### Invitations and first sign-in (Entra / OIDC)

- **Record invitation** picks the scope’s identity provider (or asks you to choose when several are linked). Invitations store `ExpectedProviderID`; pending duplicates for the same email return **GS409**.
- **No invitation email** is sent from the platform host unless you add outbound email. Use **Copy sign-in link** (`/login`) so the user opens the correct OIDC provider.
- On **first sign-in**, the host passes verified `email` / `preferred_username` claims in the auth snapshot. The portal:
  1. Accepts a matching **pending invitation** (creates/links user, grants default role, marks `ACCEPTED`), or
  2. Links an **admin-pre-created** active user when email matches, the user belongs to the organization scope, and they have **no** external identity for that provider yet.
- Existing `ExternalIdentities` are never re-bound to a different subject. Mismatched issuer/tenant or duplicate subjects are rejected (**GS403**). Every new link is recorded in `portal.external_identity_link_audit`.
- `/app/admin/roles` — create roles, toggle permissions
- `/app/admin/permissions` — permission catalog
- Meta workbench **Security** tab — class grants and effective-permission checker
- Object editor — **Object ACL** after an instance is created

Session APIs live in `portal_session_security_admin_api.sql`; enforcement is in `portal_layered_security_enforcement.sql`.

## Production apply

After `apply_schema.sh` (includes layered security SQL) and `seed_platform_nav_tree.sql`, `organization_admin` receives `platform.security.admin` alongside existing meta permissions. **`god_architect`** receives the same operator permission and NavTree grant set, plus `platform.model.architect`, via `portal.sp_sync_god_architect_operator_entitlements()`.
