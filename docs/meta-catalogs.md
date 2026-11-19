# Catalogs as Meta classes

GoliathApp's catalogs (semantic, workflow and cfg) move into the Meta class hierarchy. Each catalog table becomes a **catalog kind**: one Meta class whose fields are the table's columns, with one Meta object per row. Meta is authoritative. The table stays as the indexed read surface that the gateway, workers and SQL APIs already use, so running code keeps working unchanged.

Generic: `workflow_engine/sql_pg/meta_catalog_projection.sql`. Kinds: `semantic_catalog_meta.sql` (this PR), with the workflow and cfg catalogs in follow-up PRs.

## How it works

| Piece | What it does |
| --- | --- |
| `"Meta".sp_catalog_register_kind(kind, class, parent, table, key_columns, label_columns)` | Creates the class under `parent` with a `Label` field and one field per column, typed by `platform/catalog/*` data types (Text, Integer, Decimal, Boolean, Timestamp, Date, Document, TextList, IntegerList). A field is required when its column is `NOT NULL` without a default. Publishes the class type and its view, and installs the table trigger. Idempotent: re-running adds new columns as fields. |
| `"Meta".sp_catalog_migrate(kind)` | Turns every row into (or refreshes) its object and removes objects whose row is gone. `"Meta".catalog_row` maps each row key to its object. |
| Meta → table | Writing a catalog object (generic object editor, `sp_obj_insert`, `sp_obj_update`, deleting the object) projects the row into the table. Values the table assigns (serial ids, defaults) are written back into the object. A column missing from the document becomes `NULL` when it is nullable and keeps its value otherwise. |
| Table → Meta | Existing writers (register procedures, seeds, gateway, workers) still write the table. A row trigger keeps the object in step, including deletes and foreign-key cascades. |
| `"Meta".fn_catalog_drift(kind)` | Lists rows where the table and Meta disagree (`missing_object`, `missing_row`, `differs`). Values are compared as typed rows. |
| `"Meta".sp_catalog_project_all(kind)` | Repair: rewrites the table from Meta, so Meta wins. |

Registering many kinds at once (`p_refresh_views => false`, then `"Meta".sp_catalog_refresh_views()`) rebuilds the class views once. Field inserts made inside a registration don't trigger a per-field rebuild (`goliath.meta_defer_view_refresh`), which keeps locks low on production.

All catalog functions run with a fixed `search_path` and UTC, so the documents do not depend on the caller's session (for example, `regtype` values are always schema-qualified). The triggers are `SECURITY DEFINER`, so roles that write catalog tables today (seeds, `goliath_portal` session procedures) need no new grants.

## Semantic catalog

| Kind | Table | Class | Key |
| --- | --- | --- | --- |
| `semantic.namespace` | `portal.semantic_namespace` | `platform/semantic/Namespace` | `code` |
| `semantic.entity` | `portal.semantic_entity` | `platform/semantic/Entity` | `id` |
| `semantic.attribute` | `portal.semantic_attribute` | `platform/semantic/Attribute` | `id` |
| `semantic.request` | `portal.semantic_request` | `platform/semantic/Request` | `id` |
| `semantic.action_binding` | `portal.semantic_action_binding` | `platform/semantic/ActionBinding` | `workflow_action_id`, `entity_id` |
| `semantic.nav_binding` | `portal.semantic_nav_binding` | `platform/semantic/NavBinding` | `id` |

The classes are `platform/*`, so only God Architect edits them in the generic editors.

## Production apply

1. Create a Neon backup branch.
2. Run `workflow_engine/sql_pg/apply_schema.sh`. It registers the kinds and migrates every row.
3. Run `workflow_engine/scripts/verify_meta_catalogs.sh`. It exits non-zero on any drift.

## Next

- Workflow catalog (`wf.workflow_action`, `wf.workflow_action_schema`, `wf.action_compile_profile`, workflow definitions and versions) and cfg catalogs (`cfg.*` documents) as further kinds, each in its own PR with a backup before apply.
- Runtime tables (instances, node executions, leases, events) stay tables. They are state, not catalog.
- `wf.data_type` stays the Meta type registry itself.
