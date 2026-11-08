# Platform host — P2 Meta hierarchy (slice 1)

Stacked on [P1 auth](platform-host-p1-auth.md). **Read-only** Meta browser and flattened-schema document validation — not full DDL/ObjValues editor.

## Server contract (PostgreSQL)

| Procedure | Purpose |
|-----------|---------|
| `portal.sp_session_meta_class_get` | Class summary + flattened/bundled JSON Schema |
| `portal.sp_session_meta_class_lineage` | Ancestors, self, descendants (`Meta.ClassClosure`) |
| `portal.sp_session_meta_class_fields` | `VClassFieldsResolved` with `is_local` |
| `portal.sp_session_get_data_type` | Session-wrapped `portal.sp_get_data_type` |

Valid session required. **Fine-grained Meta RBAC codes are not enforced in this slice** (gap documented for P2+).

## BFF routes (cookie session)

- `GET /api/meta/classes/:className`
- `GET /api/meta/classes/:className/lineage`
- `GET /api/meta/classes/:className/fields`

## UI

- `/app/meta?class=portal/NavNode` — `MetaClassExplorer` + client AJV check against **flattened** schema only.
- Child apps register custom field editors via `GoliathUiManifest.editorComponents` (keys only); host does not load child React from Python.

## Implemented vs remaining (P2)

| Area | This PR | Later P2+ |
|------|---------|-----------|
| Hierarchy browser | Yes | Cross-class search, write APIs |
| Field local/inherited | Yes | Method/link editors |
| JSON instance editor | Validate-only textarea | Generated forms, `sp_obj_*` writes |
| Permissions | Session gate only | `meta.*` RBAC on read/write |
| Workflows | Roadmap (P3) | — |

## Tests

- `workflow_engine/tests/test_portal_session_meta.py`
- `@goliath/platform-ui` AJV unit smoke
- Playwright: meta API 401 without cookie
