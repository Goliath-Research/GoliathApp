# Catalogs as Meta classes

GoliathApp's catalogs (semantic, workflow and cfg) move into the Meta class hierarchy. Each catalog table becomes a **catalog kind**: one Meta class whose fields are the table's columns, with one Meta object per row. Meta is authoritative. The table stays as the indexed read surface that the gateway, workers and SQL APIs already use, so running code keeps working unchanged.

Generic: `workflow_engine/sql_pg/meta_catalog_projection.sql`. Kinds: `semantic_catalog_meta.sql` and `wf_cfg_catalog_meta.sql`.

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

## Workflow and cfg catalogs

There are **38 catalog kinds** in total: the 6 semantic kinds above plus the workflow and cfg kinds in the table below (14 `wf.*` and 18 `cfg.*`). Registered under `platform/Entity` as `platform/wf/*` and `platform/cfg/*`. Not migrated: runtime tables (instances, node executions, leases, events, workers, start requests), `cfg.credential` (secrets), `wf.data_type` (the Meta type registry itself) and `wf.cluster`.

`cfg.portal_auth_defaults` holds only integer session and worker timeout keys (`portal_session_idle_seconds`, `portal_session_absolute_seconds`, `worker_heartbeat_seconds`, `worker_session_miss_factor`, `worker_session_max_failed_attempts`). It has no secrets.

| Kind | Table | Class | Key |
| --- | --- | --- | --- |
| `wf.action` | `wf.workflow_action` | `platform/wf/Action` | `id` |
| `wf.action_schema` | `wf.workflow_action_schema` | `platform/wf/ActionSchema` | `workflow_action_id`, `direction` |
| `wf.action_compile_profile` | `wf.action_compile_profile` | `platform/wf/ActionCompileProfile` | `action_name` |
| `wf.event_type` | `wf.event_type` | `platform/wf/EventType` | `id` |
| `wf.pipeline_stage` | `wf.pipeline_stage_map` | `platform/wf/PipelineStage` | `action_name_prefix` |
| `wf.workflow_def` | `wf.workflow_def` | `platform/wf/WorkflowDef` | `id` |
| `wf.workflow_version` | `wf.workflow_version` | `platform/wf/WorkflowVersion` | `id` |
| `wf.node` | `wf.workflow_node` | `platform/wf/Node` | `id` |
| `wf.edge` | `wf.workflow_edge` | `platform/wf/Edge` | `id` |
| `wf.input_template` | `wf.workflow_input_template` | `platform/wf/InputTemplate` | `workflow_node_id` |
| `wf.input_binding` | `wf.workflow_input_binding` | `platform/wf/InputBinding` | `id` |
| `wf.output_binding` | `wf.variable_output_binding` | `platform/wf/OutputBinding` | `id` |
| `wf.scope_default` | `wf.node_scope_default` | `platform/wf/ScopeDefault` | `id` |
| `wf.collection_binding` | `wf.workflow_collection_binding` | `platform/wf/CollectionBinding` | `id` |
| `cfg.kind_document_type` | `cfg.kind_document_type` | `platform/cfg/KindDocumentType` | `kind` |
| `cfg.analyte` | `cfg.analyte` | `platform/cfg/Analyte` | `id` |
| `cfg.storage_endpoint` | `cfg.storage_endpoint` | `platform/cfg/StorageEndpoint` | `id` |
| `cfg.storage_profile` | `cfg.storage_profile` | `platform/cfg/StorageProfile` | `id` |
| `cfg.reference_asset` | `cfg.reference_asset` | `platform/cfg/ReferenceAsset` | `id` |
| `cfg.site` | `cfg.site` | `platform/cfg/Site` | `id` |
| `cfg.site_reference_asset` | `cfg.site_reference_asset` | `platform/cfg/SiteReferenceAsset` | `id` |
| `cfg.pipeline_profile` | `cfg.pipeline_profile` | `platform/cfg/PipelineProfile` | `id` |
| `cfg.enrichment_library_preset` | `cfg.enrichment_library_preset` | `platform/cfg/EnrichmentLibraryPreset` | `id` |
| `cfg.action_definition` | `cfg.action_definition` | `platform/cfg/ActionDefinition` | `id` |
| `cfg.domain_program` | `cfg.domain_program` | `platform/cfg/DomainProgram` | `id` |
| `cfg.program_publish` | `cfg.program_publish` | `platform/cfg/ProgramPublish` | `id` |
| `cfg.assay_procedure` | `cfg.assay_procedure` | `platform/cfg/AssayProcedure` | `id` |
| `cfg.node_config` | `cfg.node_config` | `platform/cfg/NodeConfig` | `id` |
| `cfg.portal_auth_default` | `cfg.portal_auth_defaults` | `platform/cfg/PortalAuthDefault` | `key` |
| `cfg.study` | `cfg.study` | `platform/cfg/Study` | `id` |
| `cfg.study_group` | `cfg.study_group` | `platform/cfg/StudyGroup` | `id` |
| `cfg.study_group_member` | `cfg.study_group_member` | `platform/cfg/StudyGroupMember` | `id` |

Runtime tables stay tables. They are state, not catalog.
