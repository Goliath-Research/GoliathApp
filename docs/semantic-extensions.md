# Semantic extensions

GoliathApp ships a **core** semantic catalog (`core.*` requests) in `goliath_app/semantic/catalog.py`. Descendant applications add entities and requests without forking the runner. Registration happens in PostgreSQL; Python models and `schemas/semantic/catalog.json` stay in sync through `goliath-semantic-export`.

## Namespaces

| Namespace | Owner | Purpose |
|-----------|--------|---------|
| `core` | GoliathApp | Platform tenancy reads (organizations today) |
| `engine` | GoliathApp | Reserved for workflow-adjacent portal reads |

Each namespace row lives in `portal.semantic_namespace`. Application apply scripts insert additional namespaces and registry rows, then run `seed_semantic_catalog.py` or an app-specific seeder that calls `portal.sp_semantic_register_*`.

## Registering entities and requests

Administrators and release automation use **registration procedures** (not the `goliath_portal` role):

- `portal.sp_semantic_register_entity`
- `portal.sp_semantic_register_attribute`
- `portal.sp_semantic_register_request`

The committed export (`goliath-semantic-export`) generates:

- Pydantic row and parameter models
- `portal_semantic_row_types.sql` composite types
- `schemas/semantic/catalog.json` for drift checks in CI

After changing Python specs, regenerate the SQL and JSON, apply schema, and seed.

## Overrides

Descendant apps can **override** a request while keeping the same `request_code` by registering a new row with a higher `version` or by replacing `target_name` / `filter_template` in apply scripts. The runner selects the row matching `p_version` (default `1`). Portal clients pass `version` to `PortalClient.run_semantic_request` when multiple versions coexist.

Filter templates use the v1 compiler (`portal.fn_semantic_compile_filter` internally). Supported predicate ops for template targets are documented in [semantic-layer.md](semantic-layer.md). Custom filter shapes that are not in the whitelist return SQLSTATE `GS501`.

## Authorization

Every `portal.semantic_request` row may set `required_permission`. At runtime `portal.sp_run_semantic_request` checks `portal.fn_semantic_session_has_permission` against `"RBAC"."UserRoleGrants"` and `"RBAC"."Role_Permissions"`.

Organization-scoped reads additionally enforce membership through `portal.fn_semantic_user_organization_ids` inside core list/filter functions. A user cannot pass another tenant's `organization_id` even when the request is otherwise allowed.

Sensitive reads should **always** enforce scope in SQL. GraphQL or MCP façades must not skip these checks.

## Auth policy hooks

`portal.auth_policy` and `portal.sp_auth_register_policy` let an installation point namespace-specific policy functions. Session idle and absolute lifetimes come from `cfg.fn_portal_auth_int` keys `portal_session_idle_seconds` and `portal_session_absolute_seconds` (see [RBAC](rbac.md)).

## Portal client

Application backends connect as `goliath_portal` and call only `portal.sp_*` entry points. See [semantic-layer.md](semantic-layer.md#python-portal-client) for `goliath_app.portal.PortalClient`.
