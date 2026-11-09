# Platform host — P2 Meta slice 3 (SchemaPropertyGrid + authenticated E2E)

Follows merged PR #62 (scoped instance APIs + anti-oracle 404/403 rules).

## SchemaPropertyGrid (canonical editor)

**Evidence in this repo:** there is no prior React `SchemaPropertyGrid` source in git history on `main`. The name and contract come from PostgreSQL/Delphi-era comments that bind UI to JSON Schema on catalog types:

```1:3:workflow_engine/sql_pg/wf_data_type.sql
-- Explicit wf data type registry.
-- schema_json is the JSON Schema document SchemaPropertyGrid binds.
```

Slice 3 **ports that contract** to `@goliath/platform-ui` as `SchemaPropertyGrid` (`packages/platform-ui/src/meta/SchemaPropertyGrid.tsx`):

- **Vertical grid:** `g-meta-field-form` + one `g-meta-field-row` per Meta field (same layout as slice‑2 `MetaGeneratedFieldForm`, not a second parallel UX).
- **Editor dispatch:** `resolveFieldEditor` → `parseFlattenedFieldSchema` on flattened class schema; Meta field `typeKind` when schema property missing.
- **Child hooks:** host `editorComponents` + `resolveMetaEditorManifestKey` renders above the grid via `MetaClassExplorer` `editorSlot` (ancestor walk, same pattern as icon overrides).

Aliases kept for compatibility: `MetaGeneratedFieldForm`, `MetaSchemaDocumentForm` delegate to `SchemaPropertyGrid`.

## Authenticated E2E (CI)

Disposable Postgres in the **frontend** GHA job:

1. `scripts/ci/platform_host_e2e_pg_seed.py` — `apply_schema.sh`, scoped `meta.*` grants, writes `apps/platform-host/.e2e/ci.env`
2. `PLAYWRIGHT_AUTH_E2E=1` — `auth.setup.ts` + `host.meta.authenticated.spec.ts`
3. Dev login (`GOLIATH_PLATFORM_HOST_DEV_LOGIN=1` + `GOLIATH_PLATFORM_HOST_E2E_INTEGRATION=1` on standalone build). `x-goliath-dev-login-user-id` is **ignored** locally and **allowlist-only** in CI (`GOLIATH_P1_DEV_LOGIN_USER_ID`, `GOLIATH_E2E_DENIED_USER_ID`); any other value returns **403** before `portal.sp_session_open` (see `resolveDevEstablishUserId`).

Coverage: icons/override slot, BFF create/get/patch, 400 invalid field, cross-scope vs missing **404** body match, permission **403**, screenshot artifact `platform-host-e2e-screenshots`.

## Gaps (honest)

- Full nested grid without JSON fallback; no production OIDC Playwright path; Delphi desktop `SchemaPropertyGrid` UI itself is **not** in this monorepo — only the SQL naming contract above.

## Not in this slice (P3+)

Workflow designer/monitor unchanged.
