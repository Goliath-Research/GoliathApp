/*
  Workflow and cfg catalogs in Meta (generic catalog projection, meta_catalog_projection.sql).
  Definitions only: runtime state (instances, node executions, leases, events, workers, start
  requests, search trials) stays in tables. cfg.credential is not migrated (secret material),
  and neither is wf.data_type, which is the Meta type registry itself.
  Idempotent: registers the kinds, then migrates every row (parents first).
*/

BEGIN;

CREATE TEMP TABLE _catalog_kinds (ord int, kind text, class_name text, relation regclass, keys text[], labels text[]) ON COMMIT DROP;
INSERT INTO _catalog_kinds VALUES
  -- workflow catalog
  (10, 'wf.action', 'platform/wf/Action', 'wf.workflow_action', ARRAY['id'], ARRAY['action_name']),
  (11, 'wf.action_schema', 'platform/wf/ActionSchema', 'wf.workflow_action_schema', ARRAY['workflow_action_id', 'direction'], ARRAY['schema_id']),
  (12, 'wf.action_compile_profile', 'platform/wf/ActionCompileProfile', 'wf.action_compile_profile', ARRAY['action_name'], ARRAY['action_name']),
  (13, 'wf.event_type', 'platform/wf/EventType', 'wf.event_type', ARRAY['id'], ARRAY['name']),
  (14, 'wf.pipeline_stage', 'platform/wf/PipelineStage', 'wf.pipeline_stage_map', ARRAY['action_name_prefix'], ARRAY['action_name_prefix', 'stage_key']),
  (20, 'wf.workflow_def', 'platform/wf/WorkflowDef', 'wf.workflow_def', ARRAY['id'], ARRAY['name']),
  (21, 'wf.workflow_version', 'platform/wf/WorkflowVersion', 'wf.workflow_version', ARRAY['id'], ARRAY['workflow_def_id', 'version_major', 'version_minor']),
  (22, 'wf.node', 'platform/wf/Node', 'wf.workflow_node', ARRAY['id'], ARRAY['node_key']),
  (23, 'wf.edge', 'platform/wf/Edge', 'wf.workflow_edge', ARRAY['id'], ARRAY['parent_node_id', 'child_node_id']),
  (24, 'wf.input_template', 'platform/wf/InputTemplate', 'wf.workflow_input_template', ARRAY['workflow_node_id'], ARRAY['workflow_node_id']),
  (25, 'wf.input_binding', 'platform/wf/InputBinding', 'wf.workflow_input_binding', ARRAY['id'], ARRAY['target_json_path']),
  (26, 'wf.output_binding', 'platform/wf/OutputBinding', 'wf.variable_output_binding', ARRAY['id'], ARRAY['var_name']),
  (27, 'wf.scope_default', 'platform/wf/ScopeDefault', 'wf.node_scope_default', ARRAY['id'], ARRAY['var_name']),
  (28, 'wf.collection_binding', 'platform/wf/CollectionBinding', 'wf.workflow_collection_binding', ARRAY['id'], ARRAY['scope_var']),
  -- cfg catalog
  (40, 'cfg.kind_document_type', 'platform/cfg/KindDocumentType', 'cfg.kind_document_type', ARRAY['kind'], ARRAY['kind']),
  (41, 'cfg.analyte', 'platform/cfg/Analyte', 'cfg.analyte', ARRAY['id'], ARRAY['name', 'version']),
  (42, 'cfg.storage_endpoint', 'platform/cfg/StorageEndpoint', 'cfg.storage_endpoint', ARRAY['id'], ARRAY['name', 'version']),
  (43, 'cfg.storage_profile', 'platform/cfg/StorageProfile', 'cfg.storage_profile', ARRAY['id'], ARRAY['name', 'version']),
  (44, 'cfg.reference_asset', 'platform/cfg/ReferenceAsset', 'cfg.reference_asset', ARRAY['id'], ARRAY['name', 'version']),
  (45, 'cfg.site', 'platform/cfg/Site', 'cfg.site', ARRAY['id'], ARRAY['name', 'version']),
  (46, 'cfg.site_reference_asset', 'platform/cfg/SiteReferenceAsset', 'cfg.site_reference_asset', ARRAY['id'], ARRAY['asset_role']),
  (47, 'cfg.pipeline_profile', 'platform/cfg/PipelineProfile', 'cfg.pipeline_profile', ARRAY['id'], ARRAY['name', 'version']),
  (48, 'cfg.enrichment_library_preset', 'platform/cfg/EnrichmentLibraryPreset', 'cfg.enrichment_library_preset', ARRAY['id'], ARRAY['name', 'version']),
  (49, 'cfg.action_definition', 'platform/cfg/ActionDefinition', 'cfg.action_definition', ARRAY['id'], ARRAY['name', 'version']),
  (50, 'cfg.domain_program', 'platform/cfg/DomainProgram', 'cfg.domain_program', ARRAY['id'], ARRAY['name', 'version']),
  (51, 'cfg.program_publish', 'platform/cfg/ProgramPublish', 'cfg.program_publish', ARRAY['id'], ARRAY['domain_program_id', 'workflow_version_id']),
  (52, 'cfg.assay_procedure', 'platform/cfg/AssayProcedure', 'cfg.assay_procedure', ARRAY['id'], ARRAY['name', 'version']),
  (53, 'cfg.node_config', 'platform/cfg/NodeConfig', 'cfg.node_config', ARRAY['id'], ARRAY['workflow_node_id']),
  (54, 'cfg.portal_auth_default', 'platform/cfg/PortalAuthDefault', 'cfg.portal_auth_defaults', ARRAY['key'], ARRAY['key']),
  (55, 'cfg.study', 'platform/cfg/Study', 'cfg.study', ARRAY['id'], ARRAY['name', 'version']),
  (56, 'cfg.study_group', 'platform/cfg/StudyGroup', 'cfg.study_group', ARRAY['id'], ARRAY['label']),
  (57, 'cfg.study_group_member', 'platform/cfg/StudyGroupMember', 'cfg.study_group_member', ARRAY['id'], ARRAY['processing_sample_key']);

SELECT count("Meta".sp_catalog_register_kind(k.kind, k.class_name, 'platform/Entity', k.relation, k.keys, k.labels,
         p_refresh_views => false))
FROM (SELECT * FROM _catalog_kinds ORDER BY ord) k;
SELECT "Meta".sp_catalog_refresh_views();

SELECT m.* FROM (SELECT * FROM _catalog_kinds ORDER BY ord) k
CROSS JOIN LATERAL "Meta".sp_catalog_migrate(k.kind) m;

COMMIT;
