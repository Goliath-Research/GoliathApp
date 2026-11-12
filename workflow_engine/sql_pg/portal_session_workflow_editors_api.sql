/*
  Workflow graph editor and run inspector for the platform host (session-gated, goliath_portal).

  Graph editing never changes a version in place: saving produces a NEW, INACTIVE
  wf.workflow_version of the same definition (next minor of the base version's major), built
  through wf.wf_repo_create_workflow_graph_version. Activation is an explicit, separate step.
  Node input templates are carried over by node_key from the base version (they are typed by
  each action's input schema and are not edited here). Event subscriptions stay attached to the
  version they reference; repoint them in the subscriptions editor when activating.

  Writers require a session, the page's NavTree leaf entitlement and platform.model.author, and
  are audited in portal.record_editor_audit.
*/

/* Export a version graph as an editable spec (WorkflowDefinitionSpec shape, keys not ids). */
CREATE OR REPLACE FUNCTION wf.wf_workflow_version_export_spec(p_workflow_version_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
-- plpgsql (not sql) so the body binds at call time: some node columns are added by later
-- schema files (wf_event_plane.sql).
BEGIN
  RETURN (
  SELECT jsonb_build_object(
    'name', d.name,
    'description', d.description,
    'root_node_key', rn.node_key,
    'nodes', COALESCE((
      SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
        'node_key', n.node_key,
        'node_type', n.node_type,
        'action_name', a.action_name,
        'repeat_count', n.repeat_count,
        'condition_ref_node_key', n.condition_ref_node_key,
        'switch_ref_node_key', n.switch_ref_node_key,
        'condition_var', n.condition_var,
        'switch_var', n.switch_var,
        'foreach_collection_var', n.foreach_collection_var,
        'foreach_item_var', n.foreach_item_var,
        'foreach_index_var', n.foreach_index_var,
        'foreach_parallel', n.foreach_parallel,
        'wait_event_type', n.wait_event_type,
        'wait_correlation_var', n.wait_correlation_var,
        'schedule_interval_seconds', n.schedule_interval_seconds,
        'input_template', t.template_json
      )) ORDER BY n.id)
      FROM wf.workflow_node n
      LEFT JOIN wf.workflow_action a ON a.id = n.workflow_action_id
      LEFT JOIN LATERAL (
        SELECT it.template_json FROM wf.workflow_input_template it
        WHERE it.workflow_node_id = n.id ORDER BY it.id DESC LIMIT 1
      ) t ON true
      WHERE n.workflow_version_id = v.id
    ), '[]'::jsonb),
    'edges', COALESCE((
      SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
        'parent_node_key', pn.node_key,
        'child_node_key', cn.node_key,
        'child_order', e.child_order,
        'branch_kind', e.branch_kind,
        'condition_expr', e.condition_expr,
        'switch_case_value', e.switch_case_value,
        'is_default', e.is_default
      )) ORDER BY pn.id, e.child_order, e.id)
      FROM wf.workflow_edge e
      JOIN wf.workflow_node pn ON pn.id = e.parent_node_id
      JOIN wf.workflow_node cn ON cn.id = e.child_node_id
      WHERE pn.workflow_version_id = v.id
    ), '[]'::jsonb),
    'input_bindings', COALESCE((
      SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
        'node_key', n.node_key, 'target_json_path', b.target_json_path,
        'source_expr', b.source_expr, 'is_required', b.is_required
      )) ORDER BY b.id)
      FROM wf.workflow_input_binding b JOIN wf.workflow_node n ON n.id = b.workflow_node_id
      WHERE n.workflow_version_id = v.id
    ), '[]'::jsonb),
    'output_bindings', COALESCE((
      SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
        'node_key', n.node_key, 'var_name', b.var_name,
        'source_kind', b.source_kind, 'source_json_path', b.source_json_path
      )) ORDER BY b.id)
      FROM wf.variable_output_binding b JOIN wf.workflow_node n ON n.id = b.workflow_node_id
      WHERE n.workflow_version_id = v.id
    ), '[]'::jsonb),
    'scope_defaults', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'node_key', n.node_key, 'var_name', sd.var_name, 'default_expr', sd.default_expr
      ) ORDER BY sd.id)
      FROM wf.node_scope_default sd JOIN wf.workflow_node n ON n.id = sd.workflow_node_id
      WHERE n.workflow_version_id = v.id
    ), '[]'::jsonb),
    'collection_bindings', COALESCE((
      SELECT jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
        'bind_order', cb.bind_order, 'scope_var', cb.scope_var, 'kind', cb.source_kind,
        'path_var', cb.path_var, 'base_var', cb.base_var, 'json_path', cb.json_path
      )) ORDER BY cb.bind_order, cb.id)
      FROM wf.workflow_collection_binding cb
      WHERE cb.workflow_version_id = v.id
    ), '[]'::jsonb)
  )
  FROM wf.workflow_version v
  JOIN wf.workflow_def d ON d.id = v.workflow_def_id
  LEFT JOIN wf.workflow_node rn ON rn.id = v.root_node_id
  WHERE v.id = p_workflow_version_id
  );
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_graph_versions(p_session_token text)
RETURNS TABLE (
  workflow_version_id bigint,
  workflow_def_id bigint,
  workflow_def_name text,
  version text,
  is_active boolean,
  node_count integer,
  run_count bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(
    p_session_token, ARRAY['/app/workflows/definitions', '/app/workflows/steps']
  );
  RETURN QUERY
  SELECT v.id, d.id, d.name, format('%s.%s', v.version_major, v.version_minor), v.is_active,
         (SELECT count(*)::int FROM wf.workflow_node n WHERE n.workflow_version_id = v.id),
         (SELECT count(*) FROM wf.workflow_instance i WHERE i.workflow_version_id = v.id)
  FROM wf.workflow_version v
  JOIN wf.workflow_def d ON d.id = v.workflow_def_id
  ORDER BY d.name, v.version_major DESC, v.version_minor DESC;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_get_workflow_version_spec(
  p_session_token text,
  p_workflow_version_id bigint
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
DECLARE
  v_doc jsonb;
BEGIN
  PERFORM portal.fn_session_require_any_nav(
    p_session_token, ARRAY['/app/workflows/definitions', '/app/workflows/steps']
  );
  SELECT jsonb_build_object(
    'workflow_version_id', v.id,
    'workflow_def_id', d.id,
    'workflow_def_name', d.name,
    'version_major', v.version_major,
    'version_minor', v.version_minor,
    'is_active', v.is_active,
    'spec', wf.wf_workflow_version_export_spec(v.id)
  )
  INTO v_doc
  FROM wf.workflow_version v
  JOIN wf.workflow_def d ON d.id = v.workflow_def_id
  WHERE v.id = p_workflow_version_id;
  IF v_doc IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'workflow version not found');
  END IF;
  RETURN v_doc;
END;
$$;

/*
  Save an edited graph as a new inactive version of the base version's definition.
  Document keys (all optional; omitted keys keep the base version's value):
    root_node_key, nodes, edges, input_bindings, output_bindings,
    scope_defaults, collection_bindings.
  (description is definition-level metadata shown in the editor but not changed here.)
  Node input_template values come from the base version by node_key.
*/
CREATE OR REPLACE FUNCTION portal.sp_session_save_workflow_version(
  p_session_token text,
  p_base_workflow_version_id bigint,
  p_document jsonb
)
RETURNS TABLE (workflow_version_id bigint, version_major int, version_minor int, is_active boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_ctx record;
  v_doc jsonb := COALESCE(p_document, '{}'::jsonb);
  v_base record;
  v_base_spec jsonb;
  v_templates jsonb;
  v_spec jsonb;
  v_nodes jsonb := '[]'::jsonb;
  v_node jsonb;
  v_minor int;
  v_result jsonb;
  v_new_id bigint;
  v_key text;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(
    p_session_token, ARRAY['/app/workflows/definitions', '/app/workflows/steps']
  ) LIMIT 1;

  SELECT v.id, v.workflow_def_id, v.version_major INTO v_base
  FROM wf.workflow_version v WHERE v.id = p_base_workflow_version_id;
  IF v_base.id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'base workflow version not found');
  END IF;
  IF jsonb_typeof(v_doc) <> 'object' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'document must be an object');
  END IF;
  FOREACH v_key IN ARRAY ARRAY['nodes', 'edges', 'input_bindings', 'output_bindings', 'scope_defaults',
                               'collection_bindings']
  LOOP
    IF v_doc ? v_key AND jsonb_typeof(v_doc->v_key) <> 'array' THEN
      PERFORM portal.fn_semantic_raise('GS400', format('%s must be a list', v_key));
    END IF;
  END LOOP;

  v_base_spec := wf.wf_workflow_version_export_spec(v_base.id);
  SELECT COALESCE(jsonb_object_agg(n->>'node_key', n->'input_template'), '{}'::jsonb)
  INTO v_templates
  FROM jsonb_array_elements(v_base_spec->'nodes') n
  WHERE n ? 'input_template';

  FOR v_node IN SELECT value FROM jsonb_array_elements(COALESCE(v_doc->'nodes', v_base_spec->'nodes'))
  LOOP
    IF jsonb_typeof(v_node) <> 'object' OR portal.fn_doc_text(v_node, 'node_key') IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS400', 'every node needs a node_key');
    END IF;
    v_node := v_node - 'input_template';
    IF v_templates ? (v_node->>'node_key') THEN
      v_node := v_node || jsonb_build_object('input_template', v_templates->(v_node->>'node_key'));
    END IF;
    v_nodes := v_nodes || jsonb_build_array(v_node);
  END LOOP;
  IF jsonb_array_length(v_nodes) = 0 THEN
    PERFORM portal.fn_semantic_raise('GS400', 'a workflow version needs at least one node');
  END IF;

  SELECT COALESCE(max(v.version_minor), -1) + 1 INTO v_minor
  FROM wf.workflow_version v
  WHERE v.workflow_def_id = v_base.workflow_def_id AND v.version_major = v_base.version_major;

  v_spec := jsonb_build_object(
    'name', v_base_spec->>'name',
    'root_node_key', COALESCE(portal.fn_doc_text(v_doc, 'root_node_key'), v_base_spec->>'root_node_key'),
    'version_major', v_base.version_major,
    'version_minor', v_minor,
    'is_active', false,
    'nodes', v_nodes,
    'edges', COALESCE(v_doc->'edges', v_base_spec->'edges'),
    'input_bindings', COALESCE(v_doc->'input_bindings', v_base_spec->'input_bindings'),
    'output_bindings', COALESCE(v_doc->'output_bindings', v_base_spec->'output_bindings'),
    'scope_defaults', COALESCE(v_doc->'scope_defaults', v_base_spec->'scope_defaults'),
    'collection_bindings', COALESCE(v_doc->'collection_bindings', v_base_spec->'collection_bindings')
  );

  BEGIN
    v_result := wf.wf_repo_create_workflow_graph_version(v_base.workflow_def_id, v_spec);
  EXCEPTION WHEN raise_exception OR invalid_text_representation OR not_null_violation
                 OR unique_violation OR check_violation OR foreign_key_violation THEN
    PERFORM portal.fn_semantic_raise('GS400', 'invalid workflow graph: ' || SQLERRM);
  END;
  v_new_id := (v_result->>'workflow_version_id')::bigint;

  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'workflow_version', 'save_new_version',
    v_new_id::text, jsonb_build_object('base_workflow_version_id', v_base.id)
  );

  RETURN QUERY
  SELECT v.id, v.version_major, v.version_minor, v.is_active
  FROM wf.workflow_version v WHERE v.id = v_new_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_activate_workflow_version(
  p_session_token text,
  p_workflow_version_id bigint
)
RETURNS TABLE (workflow_version_id bigint, version_major int, version_minor int, is_active boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(
    p_session_token, ARRAY['/app/workflows/definitions', '/app/workflows/steps']
  ) LIMIT 1;
  IF NOT EXISTS (SELECT 1 FROM wf.workflow_version v WHERE v.id = p_workflow_version_id) THEN
    PERFORM portal.fn_semantic_raise('GS404', 'workflow version not found');
  END IF;
  PERFORM 1 FROM portal.sp_activate_workflow_version(p_workflow_version_id);
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'workflow_version', 'activate',
    p_workflow_version_id::text, '{}'::jsonb
  );
  RETURN QUERY
  SELECT v.id, v.version_major, v.version_minor, v.is_active
  FROM wf.workflow_version v WHERE v.id = p_workflow_version_id;
END;
$$;

-- ── Run inspector ────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_get_run(
  p_session_token text,
  p_workflow_instance_id bigint
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, cfg, pg_temp
AS $$
DECLARE
  v_doc jsonb;
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/runs');
  SELECT jsonb_build_object(
    'workflow_instance_id', i.id,
    'workflow_def_name', d.name,
    'workflow_version_id', v.id,
    'version', format('%s.%s', v.version_major, v.version_minor),
    'status', i.status,
    'started_at_utc', i.started_at_utc,
    'completed_at_utc', i.completed_at_utc,
    'nodes', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'node_execution_id', ne.id,
        'node_key', n.node_key,
        'node_type', n.node_type,
        'action_name', a.action_name,
        'status', ne.status,
        'attempt_no', ne.attempt_no,
        'iteration_no', ne.iteration_no,
        'parent_node_execution_id', ne.parent_node_execution_id,
        'started_at_utc', ne.started_at_utc,
        'ended_at_utc', ne.ended_at_utc,
        'error_message', ne.engine_error_message
      ) ORDER BY ne.id)
      FROM wf.node_execution ne
      JOIN wf.workflow_node n ON n.id = ne.workflow_node_id
      LEFT JOIN wf.workflow_action a ON a.id = n.workflow_action_id
      WHERE ne.workflow_instance_id = i.id
    ), '[]'::jsonb),
    'variables', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'scope_node_execution_id', sv.scope_node_execution_id,
        'name', sv.var_name,
        'value', sv.value_json,
        'updated_at_utc', sv.updated_at_utc
      ) ORDER BY sv.scope_node_execution_id NULLS FIRST, sv.var_name)
      FROM wf.scope_variable sv
      WHERE sv.workflow_instance_id = i.id
    ), '[]'::jsonb),
    'study', (
      SELECT jsonb_build_object('study_row_id', s.id, 'study_id', s.study_id, 'name', s.name)
      FROM cfg.study_instance_link l JOIN cfg.study s ON s.id = l.study_row_id
      WHERE l.workflow_instance_id = i.id
    )
  )
  INTO v_doc
  FROM wf.workflow_instance i
  JOIN wf.workflow_version v ON v.id = i.workflow_version_id
  JOIN wf.workflow_def d ON d.id = v.workflow_def_id
  WHERE i.id = p_workflow_instance_id;
  IF v_doc IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'workflow run not found');
  END IF;
  RETURN v_doc;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_cancel_run(
  p_session_token text,
  p_workflow_instance_id bigint,
  p_reason text DEFAULT NULL
)
RETURNS TABLE (workflow_instance_id bigint, status text, queued_cancelled bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_ctx record;
  r record;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/runs']) LIMIT 1;
  BEGIN
    SELECT * INTO r FROM portal.sp_cancel_instance(p_workflow_instance_id, p_reason, false) LIMIT 1;
  EXCEPTION WHEN raise_exception THEN
    PERFORM portal.fn_semantic_raise('GS409', SQLERRM);
  END;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'workflow_run', 'cancel',
    p_workflow_instance_id::text, jsonb_build_object('reason', p_reason)
  );
  RETURN QUERY SELECT r.workflow_instance_id, r.status, r.queued_cancelled;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_retry_run_node(
  p_session_token text,
  p_node_execution_id bigint
)
RETURNS TABLE (node_execution_id bigint, status text, attempt_no int, instance_status text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_ctx record;
  r record;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/runs']) LIMIT 1;
  BEGIN
    SELECT * INTO r FROM portal.sp_retry_failed_node(p_node_execution_id) LIMIT 1;
  EXCEPTION WHEN raise_exception THEN
    PERFORM portal.fn_semantic_raise('GS409', SQLERRM);
  END;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'workflow_run', 'retry_node',
    p_node_execution_id::text, '{}'::jsonb
  );
  RETURN QUERY SELECT r.node_execution_id, r.status, r.attempt_no, r.instance_status;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_link_run_study(
  p_session_token text,
  p_workflow_instance_id bigint,
  p_study_row_id bigint
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, cfg, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_id bigint;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/runs']) LIMIT 1;
  BEGIN
    SELECT l.id INTO v_id FROM portal.sp_link_study_instance(p_study_row_id, p_workflow_instance_id) l;
  EXCEPTION WHEN raise_exception THEN
    PERFORM portal.fn_semantic_raise('GS400', SQLERRM);
  END;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'workflow_run', 'link_study',
    p_workflow_instance_id::text, jsonb_build_object('study_row_id', p_study_row_id)
  );
  RETURN v_id;
END;
$$;
