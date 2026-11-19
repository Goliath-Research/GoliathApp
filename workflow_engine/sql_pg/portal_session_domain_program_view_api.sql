/*
  Read-only domain program structure for the platform host (session-gated, goliath_portal).
  Returns the stored program document's structural parts (variables, declarations, phases,
  body, event triggers) and the compiled workflow version it is linked to, so the host can
  show a structure tree and open the compiled graph. Never writes.
*/

CREATE OR REPLACE FUNCTION portal.sp_session_get_domain_program_structure(
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
  v_doc jsonb;
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/domain-programs');
  SELECT jsonb_build_object(
    'name', dp.name,
    'version', dp.version,
    'status', dp.status,
    'description', dp.document_json->>'description',
    'program_version', dp.document_json->'programVersion',
    'project_path', dp.document_json->>'projectPath',
    'variables', COALESCE(dp.document_json->'variables', '{}'::jsonb),
    'declarations', COALESCE(dp.document_json->'declarations', '{}'::jsonb),
    'phases', COALESCE(dp.document_json->'phases', '[]'::jsonb),
    'body', COALESCE(dp.document_json->'body', '[]'::jsonb),
    'on', COALESCE(dp.document_json->'on', '[]'::jsonb),
    'compiled_workflow_version_id', dp.compiled_workflow_version_id,
    'compiled_workflow_name', wd.name,
    'compiled_version', CASE WHEN wv.id IS NULL THEN NULL
                             ELSE wv.version_major::text || '.' || wv.version_minor::text END,
    'compiled_is_active', wv.is_active
  )
  INTO v_doc
  FROM cfg.domain_program dp
  LEFT JOIN wf.workflow_version wv ON wv.id = dp.compiled_workflow_version_id
  LEFT JOIN wf.workflow_def wd ON wd.id = wv.workflow_def_id
  WHERE dp.name = p_name AND dp.version = p_version;
  IF v_doc IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'domain program not found');
  END IF;
  RETURN v_doc;
END;
$$;
