/*
  GoliathApp wf schema - PostgreSQL admin procedures.
  Prerequisites: 00_schema.sql
*/

CREATE OR REPLACE FUNCTION wf.sp_delete_workflow_def(
  p_workflow_def_id bigint DEFAULT NULL,
  p_workflow_name text DEFAULT NULL,
  p_delete_instances boolean DEFAULT true
)
RETURNS TABLE (deleted_instance_count int, deleted_version_count int)
LANGUAGE plpgsql
AS $$
DECLARE
  v_def_id bigint := p_workflow_def_id;
  v_inst int := 0;
  v_ver int := 0;
  v_ids bigint[];
BEGIN
  IF v_def_id IS NULL AND (p_workflow_name IS NULL OR btrim(p_workflow_name) = '') THEN
    RAISE EXCEPTION 'Provide p_workflow_def_id or p_workflow_name' USING ERRCODE = '50010';
  END IF;
  IF v_def_id IS NULL THEN
    SELECT wd.id INTO v_def_id FROM wf.workflow_def wd WHERE wd.name = p_workflow_name;
  END IF;
  IF v_def_id IS NULL THEN
    RAISE EXCEPTION 'Workflow definition not found' USING ERRCODE = '50011';
  END IF;

  IF p_delete_instances THEN
    -- Runs are history: they are removed only through the retention purge
    -- (wf_run_history_retention.sql), which refuses unless a policy allows it.
    SELECT array_agg(wi.id ORDER BY wi.id) INTO v_ids
    FROM wf.workflow_instance wi
    JOIN wf.workflow_version wv ON wv.id = wi.workflow_version_id
    WHERE wv.workflow_def_id = v_def_id;
    IF v_ids IS NOT NULL THEN
      SELECT count(*) FILTER (WHERE p.purged) INTO v_inst
      FROM wf.sp_purge_run_history(v_ids, 'workflow definition deleted', true) p;
    END IF;
  END IF;

  DELETE FROM wf.workflow_version wv WHERE wv.workflow_def_id = v_def_id;
  GET DIAGNOSTICS v_ver = ROW_COUNT;

  DELETE FROM wf.workflow_def wd WHERE wd.id = v_def_id;

  RETURN QUERY SELECT v_inst, v_ver;
END;
$$;
