# Platform host — P2 Meta hierarchy (slice 2)

Stacked on slice 1 (read APIs + explorer). Adds **server-authoritative RBAC** and **instance create/read/update** via real `Meta.sp_obj_*` contracts.

## Server contract (PostgreSQL)

| Permission | Used by |
|------------|---------|
| `meta.schema.read` | class get, lineage, fields, `sp_session_get_data_type`, class resolution on writes |
| `meta.object.read` | `sp_session_meta_obj_get` |
| `meta.object.write` | `sp_session_meta_obj_insert`, `sp_session_meta_obj_update` (requires **active scope** on session) |

| Procedure | Purpose |
|-----------|---------|
| `portal.fn_session_meta_require` | Valid session + named permission (`GS401` / `GS403`) |
| `portal.sp_session_meta_obj_insert` | `Meta.sp_obj_insert` after RBAC |
| `portal.sp_session_meta_obj_update` | `Meta.sp_obj_update` after RBAC |
| `portal.sp_session_meta_obj_get` | `Meta.fn_merged_obj_document` after RBAC |

Valid session is **necessary but not sufficient**. Permissions are seeded idempotently in `portal_session_meta_api.sql` (requires `portal/NavNode` catalog).

**Gaps (honest):**

- Object reads are not filtered by organization scope yet (permission-only).
- Unknown top-level keys are **rejected**, not preserved (`Meta.fn_reject_unknown_document_keys`).
- Generated forms cover primitive string/int fields only; nested refs need child `editorComponents`.
- Playwright CI has no Postgres — authenticated object smoke is Python integration + optional local host.

## BFF routes (cookie session)

- `GET /api/meta/classes/:className` (+ lineage, fields) — 403 when `meta.schema.read` missing
- `POST /api/meta/classes/:className/objects` — 403 without write permission or active scope
- `GET|PATCH /api/meta/objects/:objId` — 400 validation / 403 permission

## UI

- `/app/meta?class=portal/NavNode` — `MetaClassExplorer` with child `classIconOverrides`, `MetaGeneratedFieldForm` + BFF create/round-trip, AJV textarea.
- `GoliathUiManifest.editorComponents` keys resolve via host `meta-editor-registry.tsx` at build time.

## Tests

- `workflow_engine/tests/test_portal_session_meta.py` — GS403, scope on write, roundtrip, unknown field, revocation
- Playwright: meta class/object APIs 401 without cookie

## Remaining P2+

- Scope-isolated object reads, full generated form parity, workflow hooks (P3 roadmap unchanged)
