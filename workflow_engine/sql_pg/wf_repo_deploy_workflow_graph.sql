/*
  Non-destructive workflow graph deploy for gateway / CLI callers.

  A new name creates workflow_def + first version; an existing name adds the next minor
  version. Optional activation toggles is_active on workflow_version rows for that def.
*/

CREATE OR REPLACE FUNCTION wf.wf_repo_deploy_workflow_graph(
  p_spec jsonb,
  p_activate boolean DEFAULT true
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, pg_temp
AS $$
DECLARE
  v_name text;
  v_def_id bigint;
  v_doc jsonb;
  v_major int;
  v_next_minor int;
  v_payload jsonb;
  v_created boolean;
  v_version_id bigint;
BEGIN
  IF p_spec IS NULL THEN
    RAISE EXCEPTION 'workflow spec is required';
  END IF;

  v_name := btrim(p_spec->>'name');
  IF v_name IS NULL OR v_name = '' THEN
    RAISE EXCEPTION 'workflow spec missing name';
  END IF;

  PERFORM pg_advisory_xact_lock(749211, hashtext(v_name));

  SELECT wd.id
  INTO v_def_id
  FROM wf.workflow_def AS wd
  WHERE wd.name = v_name
  ORDER BY wd.id
  LIMIT 1
  FOR UPDATE;

  IF v_def_id IS NULL THEN
    v_doc := p_spec || jsonb_build_object('is_active', p_activate);
    v_payload := wf.wf_repo_create_workflow_graph(v_doc);
    v_created := true;
  ELSE
    v_major := COALESCE((p_spec->>'version_major')::int, 1);
    SELECT COALESCE(max(wv.version_minor), -1) + 1
    INTO v_next_minor
    FROM wf.workflow_version AS wv
    WHERE wv.workflow_def_id = v_def_id AND wv.version_major = v_major;

    v_doc := p_spec || jsonb_build_object(
      'version_major', v_major,
      'version_minor', v_next_minor,
      'is_active', false
    );
    v_payload := wf.wf_repo_create_workflow_graph_version(v_def_id, v_doc);
    v_created := false;
  END IF;

  v_version_id := (v_payload->>'workflow_version_id')::bigint;

  IF p_activate AND NOT v_created THEN
    UPDATE wf.workflow_version AS wv
    SET is_active = (wv.id = v_version_id)
  WHERE wv.workflow_def_id = (v_payload->>'workflow_def_id')::bigint;
  END IF;

  RETURN v_payload || jsonb_build_object(
    'created_definition', v_created,
    'active', p_activate
  );
END;
$$;