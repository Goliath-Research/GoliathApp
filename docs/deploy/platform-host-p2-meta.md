# Platform host — P2 Meta hierarchy (slice 2)

Stacked on slice 1. **Catalog reads** stay global; **instance data** is scope-bound on the server.

## Tenancy model (code-only DDL in `portal_session_meta_api.sql`)

| Layer | Scope behavior |
|--------|----------------|
| **Catalog** (`meta.schema.read`) | `Meta.Classes`, hierarchy, fields, `wf.data_type` — global; session + permission only (no active scope required). |
| **Instances** (`meta.object.*`) | Rows in `portal.ScopedMetaObjects` bind `Meta.Objs.ID` → `RBAC.Scopes.ScopeID` at create time. |
| **Legacy/catalog `Meta.Objs`** | No `ScopedMetaObjects` row → **not visible** via `sp_session_meta_obj_get` (`GS404`). |

Instance authorization flow:

1. `fn_session_meta_require_instance` — valid session, **non-null `ActiveScopeID`**, permission effective **in that scope** (`UserRoleGrants.ScopeID = active scope` or `BypassScope` role). **Global grants (`ScopeID` NULL) do not authorize instances.**
2. `fn_session_meta_strip_tenancy_keys` — remove forged `scope_id`, `OrganizationID`, etc. from JSON **before** `Meta.sp_obj_*`.
3. `fn_session_meta_assert_obj_in_active_scope` — `ScopedMetaObjects.ScopeID` must equal session active scope. **Cross-tenant, unmapped, and never-allocated IDs all raise `GS404` / `meta object not found`** (no existence oracle). Permission failures without object identity remain `GS403`.

**Not claimed:** org membership checks beyond RBAC grants; row-level scope inside merged JSON; preserving unknown top-level keys (rejected explicitly by phase D).

## Permissions

| Permission | Scope rule |
|------------|------------|
| `meta.schema.read` | Any matching grant (incl. global NULL `ScopeID`). |
| `meta.object.read` / `meta.object.write` | Grant must match **active session scope** (or `BypassScope`). |

## BFF routes

Same procedures as slice 1; BFF is a thin cookie forwarder — isolation is enforced in PostgreSQL.

- `POST /api/meta/classes/:className/objects`
- `GET|PATCH /api/meta/objects/:objId`

## UI limitations

- `MetaGeneratedFieldForm`: primitive string/int/checkbox inference only.
- AJV textarea validates flattened schema only; server may reject additional keys.
- Authenticated host smoke requires local Postgres + `GOLIATH_PLATFORM_HOST_DEV_LOGIN=1` (integration header); CI Playwright stays unauthenticated.

## Tests

`workflow_engine/tests/test_portal_session_meta.py`:

- Same-scope insert/get roundtrip
- Cross-scope read/update → same `GS404` as missing/unmapped (GET and PATCH)
- Indistinguishable error text across nonexistent, catalog-unmapped, and cross-scope IDs
- Null active scope on instance read/write `GS403`
- Global (unscoped) grant + active scope session → instance `GS403`
- Forged tenancy keys stripped; tenancy from session only
- Catalog object without tenancy → `GS404`
- Permission revocation → `GS403`
- Session revocation → `GS401` (schema)

## Remaining P2+

Full generated form parity, nested editors, optional org-membership assertion, P3 workflows unchanged.
