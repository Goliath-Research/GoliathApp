-- Example ONLY: minimal runnable + claimable workflow on a disposable database.
-- Not run by apply_schema.sh. Prerequisites: full apply_schema.sh + seed_action_catalog.py --use-db
-- (wf.workflow_action rows including workflow.const_string from goliath_app/engine/catalog.py).
--
-- Demonstrates, with code-backed entity names only:
--   wf.wf_repo_create_workflow_graph → wf.workflow_def / workflow_version / nodes / edges
--   cfg.domain_program → optional FK to wf.workflow_def and wf.workflow_version (see cfg_wf_relationships.sql)
--   wf.wf_repo_create_workflow_instance + wf.sp_start_workflow_instance → READY node_execution for workers
--
-- Run (operator / superuser), non-interactive:
--   psql -v ON_ERROR_STOP=1 "$DSN" -f docs_bootstrap_minimal_workflow.sql
--
-- Idempotent: deletes prior workflow def by name via wf.sp_delete_workflow_def.

BEGIN;

-- Remove previous demo graph if re-run (sp_delete_workflow_def errors when the name is missing)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM wf.workflow_def WHERE name = 'DocsBootstrapConstEcho') THEN
    PERFORM * FROM wf.sp_delete_workflow_def(NULL, 'DocsBootstrapConstEcho', true);
  END IF;
END $$;

-- Single ACTION (workflow.const_string) under a SEQUENCE root; input built from workflow_input_template only.
DO $$
DECLARE
  v_graph jsonb;
  v_payload jsonb;
  v_def_id bigint;
  v_ver_id bigint;
  v_inst_id bigint;
BEGIN
  v_graph := jsonb_build_object(
    'name', 'DocsBootstrapConstEcho',
    'description', 'Synthetic minimal graph for database population documentation',
    'root_node_key', 'root',
    'version_major', 1,
    'version_minor', 0,
    'is_active', true,
    'nodes', jsonb_build_array(
      jsonb_build_object('node_key', 'root', 'node_type', 'SEQUENCE'),
      jsonb_build_object(
        'node_key', 'say',
        'node_type', 'ACTION',
        'action_name', 'workflow.const_string',
        'input_template', jsonb_build_object('tool', 'workflow.compute', 'value', 'bootstrap')
      )
    ),
    'edges', jsonb_build_array(
      jsonb_build_object(
        'parent_node_key', 'root',
        'child_node_key', 'say',
        'child_order', 0,
        'branch_kind', 'SEQUENCE'
      )
    )
  );

  v_payload := wf.wf_repo_create_workflow_graph(v_graph);
  v_def_id := (v_payload->>'workflow_def_id')::bigint;
  v_ver_id := (v_payload->>'workflow_version_id')::bigint;

  IF NOT EXISTS (SELECT 1 FROM wf.workflow_action WHERE action_name = 'workflow.const_string') THEN
    RAISE EXCEPTION 'Missing wf.workflow_action row for workflow.const_string; run seed_action_catalog.py --use-db';
  END IF;

  -- Optional cfg row: documents the domain_program ↔ workflow linkage (FKs in cfg_wf_relationships.sql).
  INSERT INTO cfg.domain_program (
    name,
    version,
    status,
    content_hash,
    document_json,
    workflow_def_id,
    compiled_workflow_version_id
  )
  VALUES (
    'docs_bootstrap_const_echo',
    '1',
    'published',
    encode(wf.wf_sha256_text('{"programVersion":2,"name":"DocsBootstrapConstEcho"}'), 'hex'),
    jsonb_build_object(
      'programVersion', 2,
      'name', 'DocsBootstrapConstEcho',
      'description', 'Synthetic minimal document for cfg.domain_program FK demo',
      'projectPath', '/tmp',
      'variables', '{}'::jsonb,
      'body', '[]'::jsonb
    ),
    v_def_id,
    v_ver_id
  )
  ON CONFLICT (name, version) DO UPDATE SET
    content_hash = EXCLUDED.content_hash,
    document_json = EXCLUDED.document_json,
    workflow_def_id = EXCLUDED.workflow_def_id,
    compiled_workflow_version_id = EXCLUDED.compiled_workflow_version_id,
    status = EXCLUDED.status;

  SELECT id INTO v_inst_id FROM wf.wf_repo_create_workflow_instance(v_ver_id, '{}'::jsonb);
  CALL wf.sp_start_workflow_instance(v_inst_id);

  RAISE NOTICE 'workflow_def_id=%, workflow_version_id=%, instance_id=%', v_def_id, v_ver_id, v_inst_id;
END $$;

COMMIT;

-- Post-checks (read-only)
-- Expect one READY ACTION node_execution referencing workflow.const_string.
SELECT
  wi.id AS workflow_instance_id,
  wi.status AS instance_status,
  ne.id AS node_execution_id,
  ne.status AS node_execution_status,
  wa.action_name
FROM wf.workflow_instance wi
JOIN wf.node_execution ne ON ne.workflow_instance_id = wi.id
JOIN wf.workflow_node wn ON wn.id = ne.workflow_node_id
LEFT JOIN wf.workflow_action wa ON wa.id = wn.workflow_action_id
WHERE wi.id IN (
  SELECT MAX(id) FROM wf.workflow_instance
)
ORDER BY ne.id;

SELECT
  dp.name AS domain_program_name,
  dp.workflow_def_id,
  dp.compiled_workflow_version_id,
  wd.name AS workflow_def_name
FROM cfg.domain_program dp
JOIN wf.workflow_def wd ON wd.id = dp.workflow_def_id
WHERE dp.name = 'docs_bootstrap_const_echo';
