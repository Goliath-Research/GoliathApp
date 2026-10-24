# RBAC

RBAC is the `"RBAC"` schema in `workflow_engine/sql_pg/rbac_schema.sql`. Identifiers are quoted PascalCase for legacy EpiPortal compatibility. There is no lowercase `rbac` synonym schema. The gateway does not expose these procedures over HTTP. Callers use the database.

## Tables

| Table | Contents |
|-------|----------|
| `"RBAC"."Users"` | Account. Email and active flag. |
| `"RBAC"."Groups"`, `"Group_Users"`, `"Group_Roles"` | Group membership and the roles a group grants. |
| `"RBAC"."Roles"` | Role name and `BypassScope`. |
| `"RBAC"."Permissions"`, `"Role_Permissions"` | Permission is a name plus `ObjID` and `OperationID` (Meta object and operation). |
| `"RBAC"."Scopes"` | `ScopeType`, name, optional institution, lab, and owner. |
| `"RBAC"."Sessions"`, `"Session_Roles"` | A session has a user and an active scope. |
| `"RBAC"."IdentityProviders"`, `"ExternalIdentities"`, `"ScopeIdentityProviders"` | External subject bound to a user, and which providers a scope allows. |
| `"RBAC"."UserRoleGrants"` | Direct user-to-role grant. |
| `"RBAC"."BypassScopeApprovals"` | Approval row for a role whose `BypassScope` is set. |

`rbac_api_parity.sql` notes that the Azure trigger which enforces bypass-scope approval is not created on PostgreSQL. The parity file says that rule is left to the application layer for the PostgreSQL deployment.

## Portal façade

`portal_rbac_api.sql` is the administration surface. Its header states that portal screens call `portal.sp_*` and do not call `"RBAC"` write functions directly. Functions in this file include:

- Users: `portal.sp_list_users`, `portal.sp_get_user`, `portal.sp_upsert_user`, `portal.sp_list_user_identities`
- Roles and permissions: `portal.sp_list_roles`, `portal.sp_list_permissions`
- Scopes: `portal.sp_list_scopes`, `portal.sp_get_scope`
- Grants: `portal.sp_grant_user_role`, `portal.sp_list_user_role_grants`, `portal.sp_revoke_user_role`
- Groups: `portal.sp_list_user_groups`, `portal.sp_set_user_group_members`, `portal.sp_set_user_group_roles`
- Sessions: `portal.sp_list_user_sessions`, `portal.sp_revoke_user_session`
- Navigation grants: `portal.sp_list_role_nav_nodes`, `portal.sp_grant_role_nav_node`, `portal.sp_deny_role_nav_node` (table `portal."Role2Node"`)
- Invitations: `portal.sp_create_invitation_batch`, `portal.sp_create_invitation`, `portal.sp_list_invitations`, `portal.sp_revoke_invitation`
- Bypass scope: `portal.sp_list_bypass_scope_approvals`, `portal.sp_create_bypass_scope_approval`, `portal.sp_decide_bypass_scope_approval`

`"RBAC".spgetuseridbyemail` and `"RBAC".spgetuserroles` are in `rbac_api_parity.sql`. Role lookup walks group membership. `portal."viewUserAllRoles"` reads `portal."UserRoles"`, which this script creates, and copies leftover `e_portal."UserRoles"` rows when that old table is present.

Navigation uses `portal."Role2Node"` and `portal."NavTree"` from `portal_shell_schema.sql`. Contract admin APIs join `portal."Organizations"`. Clinical customer and sample tables are app-owned (see [schema-apply.md](schema-apply.md)).

Permissions point at Meta classes through `ObjID` and `OperationID`. Class rows and instances live in `"Meta"` (`meta_schema.sql`, `"Meta"."Objs"`). Meta parity procedures are `meta_api_parity.sql`.

## Organizations

Tenancy for the portal lives in `portal."Organizations"` and `portal."OrganizationMembers"` (`portal_organization_schema.sql`). Administration uses `portal.sp_organization_*` procedures (create, add member, list). Semantic organization reads (`core.list_organizations`, `core.filter_organizations`) scope rows to the caller's memberships through `portal.fn_semantic_user_organization_ids`; they do not expose cross-tenant data.

`portal.fn_session_resolve` attaches a JSON array of `{organization_id, name}` pairs to the session context for UI menus. That snapshot is informational; enforcement for reads stays in the semantic runner.

## Portal sessions

Interactive portal users authenticate into `"RBAC"."Sessions"` with bearer tokens stored as hashes in `"RBAC"."SessionTokens"`. Session lifecycle procedures are in `portal_session_api.sql`:

| Procedure | Role |
|-----------|------|
| `portal.sp_session_open` | Mint a token for an active `"RBAC"."Users"` row |
| `portal.fn_session_resolve` | Resolve token to user, scope, organizations, expiry |
| `portal.sp_session_touch` | Refresh idle expiry within policy |
| `portal.sp_session_revoke` | Revoke the current token |

Idle and absolute timeouts read `cfg` keys `portal_session_idle_seconds` and `portal_session_absolute_seconds`. Optional namespace hooks are registered with `portal.sp_auth_register_policy` (see [semantic-extensions.md](semantic-extensions.md)).

The `goliath_portal` database login may execute these session procedures plus semantic reads; it has no `USAGE` on `"RBAC"` tables. Worker fleet sessions (`wf.wf_worker_authenticate`) are separate; see [workers.md](workers.md).
