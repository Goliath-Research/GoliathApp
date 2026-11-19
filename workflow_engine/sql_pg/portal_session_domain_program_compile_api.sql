/*
  Domain program small edits and server-side compile/publish (generic).

  Action compile profiles (wf.action_compile_profile)
    What the DomainProgram compiler needs to know about each action (tool, action config key,
    context variables, domain effects). Seeded by the app that owns the action
    (seed_action_catalog.py writes one row per catalog action); the platform's own actions are
    seeded below. GoliathApp knows no application action.

  Steps
    Every action step of a draft program is a record: its parameters ("with") are edited in the
    typed inspector, typed by the action's Meta method parameters. Steps whose action has no
    typed parameters are view-only. Expression values ("${...}") stay text.

  Compile and publish
    The platform host reads the program and the profiles of the actions it uses
    (sp_session_domain_program_compile_input), compiles it with the Python compiler running on
    the server, and stores the result (sp_session_domain_program_publish_compiled): a new
    inactive workflow version (activate it on Workflow definitions) and the program published
    with a link to that version. Nothing is deleted.
*/

CREATE TABLE IF NOT EXISTS wf.action_compile_profile (
  action_name text PRIMARY KEY REFERENCES wf.workflow_action (action_name),
  tool text NULL,
  action_config_key text NULL,
  context_vars text[] NOT NULL DEFAULT '{}',
  domain_effects jsonb NULL,
  updated_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

/* Owner-only: the app that owns an action records how the compiler lowers it. */
CREATE OR REPLACE FUNCTION wf.wf_repo_upsert_action_compile_profile(
  p_action_name text,
  p_tool text,
  p_action_config_key text,
  p_context_vars text[],
  p_domain_effects jsonb
)
RETURNS void
LANGUAGE plpgsql
SET search_path = wf, pg_temp
AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM wf.workflow_action a WHERE a.action_name = p_action_name) THEN
    RAISE EXCEPTION 'action % not found', p_action_name;
  END IF;
  INSERT INTO wf.action_compile_profile (action_name, tool, action_config_key, context_vars, domain_effects)
  VALUES (p_action_name, NULLIF(p_tool, ''), NULLIF(p_action_config_key, ''), COALESCE(p_context_vars, '{}'),
          NULLIF(p_domain_effects, 'null'::jsonb))
  ON CONFLICT (action_name) DO UPDATE SET
    tool = EXCLUDED.tool,
    action_config_key = EXCLUDED.action_config_key,
    context_vars = EXCLUDED.context_vars,
    domain_effects = EXCLUDED.domain_effects,
    updated_at_utc = now() AT TIME ZONE 'utc';
END;
$$;

REVOKE ALL ON FUNCTION wf.wf_repo_upsert_action_compile_profile(text, text, text, text[], jsonb) FROM PUBLIC;

/* Platform action profiles (goliath_app platform catalogs; test_domain_program_compile checks they match). */
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT * FROM (VALUES
      ('inv.stock.adjust', 'inv.stock.adjust'),
      ('inv.stock.issue', 'inv.stock.issue'),
      ('inv.stock.receive', 'inv.stock.receive'),
      ('validation.plan_iterations', 'validation.plan-iterations'),
      ('workflow.const_bool', 'workflow.compute'),
      ('workflow.const_int', 'workflow.compute'),
      ('workflow.const_path', 'workflow.compute'),
      ('workflow.const_string', 'workflow.compute'),
      ('workflow.device_adapter.command', 'device.adapter.command'),
      ('workflow.device_adapter.observe', 'device.adapter.observe'),
      ('workflow.fs_stat', 'workflow.compute'),
      ('workflow.json_path_bool', 'workflow.compute'),
      ('workflow.json_path_int', 'workflow.compute'),
      ('workflow.json_path_string', 'workflow.compute')
    ) AS v(action_name, tool)
  LOOP
    CONTINUE WHEN NOT EXISTS (SELECT 1 FROM wf.workflow_action a WHERE a.action_name = r.action_name);
    CONTINUE WHEN EXISTS (SELECT 1 FROM wf.action_compile_profile p WHERE p.action_name = r.action_name);
    PERFORM wf.wf_repo_upsert_action_compile_profile(r.action_name, r.tool, NULL, '{}', NULL);
  END LOOP;
END;
$$;

/* Action and assign steps of a program document: path (jsonb path elements), action, parameters. */
CREATE OR REPLACE FUNCTION portal.fn_domain_program_action_steps(p_doc jsonb)
RETURNS TABLE (step_path text[], action_name text, params jsonb)
LANGUAGE sql
IMMUTABLE
AS $$
  WITH RECURSIVE walk(path, node) AS (
    SELECT ARRAY[k.key], k.value
    FROM jsonb_each(CASE WHEN jsonb_typeof(p_doc) = 'object' THEN p_doc ELSE '{}'::jsonb END) k
    WHERE k.key IN ('body', 'phases')
    UNION ALL
    SELECT w.path || c.key, c.value
    FROM walk w
    CROSS JOIN LATERAL (
      SELECT e.key, e.value FROM jsonb_each(CASE WHEN jsonb_typeof(w.node) = 'object' THEN w.node ELSE '{}'::jsonb END) e
      WHERE e.key NOT IN ('with', 'in', 'out', 'for', 'variables', 'declarations', 'on')
        AND jsonb_typeof(e.value) IN ('object', 'array')
      UNION ALL
      SELECT (a.ord - 1)::text, a.value
      FROM jsonb_array_elements(CASE WHEN jsonb_typeof(w.node) = 'array' THEN w.node ELSE '[]'::jsonb END)
        WITH ORDINALITY a(value, ord)
      WHERE jsonb_typeof(a.value) IN ('object', 'array')
    ) c
    WHERE array_length(w.path, 1) < 40
  )
  SELECT w.path,
         COALESCE(w.node->>'using', w.node->>'do', w.node->>'action'),
         COALESCE(w.node->'with', w.node->'in', '{}'::jsonb)
  FROM walk w
  WHERE jsonb_typeof(w.node) = 'object'
    AND (jsonb_typeof(w.node->'do') = 'string' OR jsonb_typeof(w.node->'action') = 'string'
         OR (w.node ? 'assign' AND jsonb_typeof(w.node->'using') = 'string'))
  ORDER BY w.path;
$$;

/* Editable schema of a step: the action's typed parameters; expression values stay text. */
CREATE OR REPLACE FUNCTION portal.fn_domain_program_step_schema(p_action_name text, p_params jsonb)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_schema jsonb := portal.fn_workflow_action_parameter_schema(p_action_name);
  v_props jsonb;
  r record;
BEGIN
  v_props := COALESCE(v_schema->'properties', '{}'::jsonb);
  IF v_props = '{}'::jsonb THEN
    RETURN NULL;
  END IF;
  FOR r IN SELECT key, value FROM jsonb_each(COALESCE(p_params, '{}'::jsonb))
  LOOP
    IF v_props ? r.key AND jsonb_typeof(r.value) = 'string' AND (r.value #>> '{}') LIKE '${%' THEN
      v_props := jsonb_set(v_props, ARRAY[r.key], jsonb_build_object(
        'type', 'string', 'description', 'Expression (bound when the workflow runs)'));
    END IF;
  END LOOP;
  -- Steps may leave parameters to defaults or context, so nothing is required here.
  RETURN jsonb_build_object('type', 'object', 'properties', v_props);
END;
$$;

REVOKE ALL ON FUNCTION portal.fn_domain_program_step_schema(text, jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION portal.sp_session_domain_program_step_list(p_session_token text)
RETURNS TABLE (
  step_key text,
  program text,
  version text,
  step_path text,
  action_name text,
  param_count integer,
  editable boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/workflows/domain-programs']);
  RETURN QUERY
  SELECT dp.name || '@' || dp.version || '#' || array_to_string(s.step_path, '.'),
         dp.name, dp.version, array_to_string(s.step_path, '.'), s.action_name,
         (SELECT count(*)::int FROM jsonb_object_keys(CASE WHEN jsonb_typeof(s.params) = 'object' THEN s.params ELSE '{}'::jsonb END)),
         portal.fn_domain_program_step_schema(s.action_name, s.params) IS NOT NULL
  FROM cfg.domain_program dp
  CROSS JOIN LATERAL portal.fn_domain_program_action_steps(dp.document_json) s
  WHERE dp.status = 'draft'
  ORDER BY dp.name, dp.version, s.step_path;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_domain_program_step_locate(p_step_key text)
RETURNS TABLE (name text, version text, step_path text[])
LANGUAGE plpgsql
IMMUTABLE
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_m text[] := regexp_match(COALESCE(p_step_key, ''), '^(.+)@([^@#]+)#([A-Za-z0-9_.]+)$');
BEGIN
  IF v_m IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'step key must be name@version#path');
  END IF;
  RETURN QUERY SELECT v_m[1], v_m[2], string_to_array(v_m[3], '.');
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_domain_program_step_get(p_session_token text, p_step_key text)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
DECLARE
  k record;
  s record;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/workflows/domain-programs']);
  SELECT * INTO k FROM portal.fn_domain_program_step_locate(p_step_key);
  SELECT st.* INTO s
  FROM cfg.domain_program dp
  CROSS JOIN LATERAL portal.fn_domain_program_action_steps(dp.document_json) st
  WHERE dp.name = k.name AND dp.version = k.version AND st.step_path = k.step_path;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'step not found');
  END IF;
  RETURN jsonb_build_object(
    'step_key', p_step_key,
    'program', k.name,
    'version', k.version,
    'step_path', array_to_string(k.step_path, '.'),
    'action_name', s.action_name,
    'document', s.params,
    'document_schema', portal.fn_domain_program_step_schema(s.action_name, s.params)
  );
END;
$$;

/* Save a step's parameters on a draft program. Document: { document: { param: value, ... } }. */
CREATE OR REPLACE FUNCTION portal.sp_session_domain_program_step_save(
  p_session_token text,
  p_step_key text,
  p_document jsonb
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
DECLARE
  v_ctx record;
  k record;
  s record;
  v_dp record;
  v_params jsonb := COALESCE(p_document->'document', '{}'::jsonb);
  v_schema jsonb;
  v_key text;
  v_new jsonb;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/domain-programs']) LIMIT 1;
  SELECT * INTO k FROM portal.fn_domain_program_step_locate(p_step_key);
  SELECT dp.status, dp.document_json INTO v_dp
  FROM cfg.domain_program dp WHERE dp.name = k.name AND dp.version = k.version
  FOR UPDATE;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'domain program not found');
  END IF;
  IF v_dp.status <> 'draft' THEN
    PERFORM portal.fn_semantic_raise('GS409', 'published versions are immutable; save the program under a new version first');
  END IF;
  SELECT st.* INTO s FROM portal.fn_domain_program_action_steps(v_dp.document_json) st WHERE st.step_path = k.step_path;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'step not found');
  END IF;
  v_schema := portal.fn_domain_program_step_schema(s.action_name, s.params);
  IF v_schema IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS409', format('action %s has no typed parameters; this step is view-only', s.action_name));
  END IF;
  -- An expression stays an expression only when its text is kept; new values follow the type.
  PERFORM portal.fn_cfg_document_check(v_schema, v_params);
  -- Parameters not declared by the action (kept from the program file) are preserved.
  v_new := v_params;
  FOR v_key IN SELECT jsonb_object_keys(COALESCE(s.params, '{}'::jsonb))
  LOOP
    IF NOT (v_schema->'properties') ? v_key THEN
      v_new := v_new || jsonb_build_object(v_key, s.params->v_key);
    END IF;
  END LOOP;
  v_new := jsonb_strip_nulls(v_new);
  v_key := CASE WHEN (v_dp.document_json #> k.step_path) ? 'in' AND NOT (v_dp.document_json #> k.step_path) ? 'with'
                THEN 'in' ELSE 'with' END;
  PERFORM 1 FROM portal.sp_upsert_domain_program(
    k.name, k.version, 'draft', jsonb_set(v_dp.document_json, k.step_path || v_key, v_new, true)
  );
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
    'domain_program_step', 'save', p_step_key, v_params
  );
  RETURN p_step_key;
END;
$$;

/* Compiler input for a draft: the program document and the compile profiles of its actions. */
CREATE OR REPLACE FUNCTION portal.sp_session_domain_program_compile_input(
  p_session_token text,
  p_name text,
  p_version text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, wf, pg_temp
AS $$
DECLARE
  v_dp record;
  v_missing text;
BEGIN
  PERFORM 1 FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/domain-programs']);
  SELECT dp.status, dp.document_json INTO v_dp
  FROM cfg.domain_program dp WHERE dp.name = p_name AND dp.version = p_version;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'domain program not found');
  END IF;
  IF v_dp.status <> 'draft' THEN
    PERFORM portal.fn_semantic_raise('GS409', 'only drafts are compiled and published');
  END IF;
  SELECT string_agg(DISTINCT s.action_name, ', ') INTO v_missing
  FROM portal.fn_domain_program_action_steps(v_dp.document_json) s
  WHERE NOT EXISTS (SELECT 1 FROM wf.action_compile_profile p WHERE p.action_name = s.action_name);
  IF v_missing IS NOT NULL THEN
    PERFORM portal.fn_semantic_raise('GS409', format(
      'no compile profile for: %s (the app that owns these actions seeds them)', v_missing));
  END IF;
  RETURN jsonb_build_object(
    'program', v_dp.document_json,
    'actions', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'action_name', p.action_name, 'tool', p.tool, 'action_config_key', p.action_config_key,
        'context_vars', to_jsonb(p.context_vars), 'domain_effects', p.domain_effects
      ) ORDER BY p.action_name)
      FROM wf.action_compile_profile p
      WHERE p.action_name IN (SELECT s.action_name FROM portal.fn_domain_program_action_steps(v_dp.document_json) s)
    ), '[]'::jsonb)
  );
END;
$$;

/* Store a compiled graph: new inactive workflow version, program published and linked. */
CREATE OR REPLACE FUNCTION portal.sp_session_domain_program_publish_compiled(
  p_session_token text,
  p_name text,
  p_version text,
  p_spec jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, cfg, wf, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_status text;
  v_deployed jsonb;
  v_wv bigint;
  v_unknown text;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/domain-programs']) LIMIT 1;
  SELECT dp.status INTO v_status FROM cfg.domain_program dp WHERE dp.name = p_name AND dp.version = p_version FOR UPDATE;
  IF v_status IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'domain program not found');
  END IF;
  IF v_status <> 'draft' THEN
    PERFORM portal.fn_semantic_raise('GS409', 'only drafts are compiled and published');
  END IF;
  IF jsonb_typeof(p_spec) <> 'object' OR p_spec->>'name' IS DISTINCT FROM p_name THEN
    PERFORM portal.fn_semantic_raise('GS400', 'compiled graph must be named after the program');
  END IF;
  SELECT string_agg(DISTINCT n->>'action_name', ', ') INTO v_unknown
  FROM jsonb_array_elements(COALESCE(p_spec->'nodes', '[]'::jsonb)) n
  WHERE n->>'node_type' = 'ACTION'
    AND NOT EXISTS (SELECT 1 FROM wf.workflow_action a WHERE a.action_name = n->>'action_name');
  IF v_unknown IS NOT NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', format('unknown actions: %s', v_unknown));
  END IF;
  v_deployed := wf.wf_repo_deploy_workflow_graph(p_spec, false);
  v_wv := (v_deployed->>'workflow_version_id')::bigint;
  PERFORM 1 FROM portal.sp_publish_domain_program(p_name, p_version, v_wv);
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
    'domain_program', 'compile_publish', p_name || '@' || p_version,
    jsonb_build_object('workflow_version_id', v_wv)
  );
  RETURN jsonb_build_object('name', p_name, 'version', p_version, 'status', 'published', 'workflow_version_id', v_wv);
END;
$$;
