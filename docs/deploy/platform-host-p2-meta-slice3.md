# Platform host — P2 Meta slice 3 (schema editors + authenticated E2E)

Follows merged PR #62 (scoped instance APIs + anti-oracle 404/403 rules).

## Schema-backed editors

- `MetaSchemaDocumentForm` reads flattened JSON Schema per field (`parseFlattenedFieldSchema`).
- Supported: string/integer/number/boolean, enums, arrays of primitives, shallow object property lists.
- **JSON fallback** (textarea) for `$ref`, `allOf`/`oneOf` branches, and other unsupported constructs — **server** `Meta.fn_reject_unknown_document_keys` still authoritative.

## Child `editorComponents`

- `resolveMetaEditorManifestKey` walks class ancestry (same spirit as icon overrides).
- Host registry binds opaque manifest keys at build time.

## Authenticated E2E (CI)

Disposable Postgres in the **frontend** GHA job:

1. `scripts/ci/platform_host_e2e_pg_seed.py` — `apply_schema.sh`, scoped `meta.*` grants, writes `apps/platform-host/.e2e/ci.env`
2. `PLAYWRIGHT_AUTH_E2E=1` — runs `auth.setup.ts` + `host.meta.authenticated.spec.ts`
3. Dev login (`GOLIATH_PLATFORM_HOST_DEV_LOGIN=1`) mints cookie sessions (integration-only)

Coverage: UI create, BFF create/get/patch roundtrip, 400 invalid field, cross-scope vs missing **404 equivalence**, permission **403**, screenshots artifact `platform-host-e2e-screenshots`.

Local VM without Postgres: only `host.smoke.spec.ts` runs (default). Same as before — no waiver.

## Not in this slice (P3+)

- Full nested generated UI without JSON fallback
- Production OIDC Playwright path
- Workflow engine hooks
