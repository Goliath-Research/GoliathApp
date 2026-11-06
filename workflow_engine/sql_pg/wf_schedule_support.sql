/*
  SCHEDULE composite: inherited periodic work inside a long-running workflow instance.

  A SCHEDULE node runs its single ACTION child, then re-enqueues that same ACTION after
  schedule_interval_seconds without a second external scheduler process.

  Deploy after 08_foreach_support.sql (replaces small parts of wf_engine_activate/continue/complete).
*/

CREATE OR REPLACE PROCEDURE wf.wf_engine_enqueue_scheduled_action(
  IN p_workflow_instance_id bigint,
  IN p_action_workflow_node_id bigint,
  IN p_parent_schedule_execution_id bigint,
  IN p_iteration_no int,
  IN p_available_at timestamptz
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_ne_id bigint;
  v_fj jsonb;
  v_failed boolean;
  v_fc int;
  v_fm text;
  v_parent_ntype text;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM wf.workflow_instance wi
    WHERE wi.id = p_workflow_instance_id AND wi.status = 'RUNNING'
  ) THEN
    RETURN;
  END IF;

  INSERT INTO wf.node_execution (
    workflow_instance_id, workflow_node_id, status, attempt_no,
    parent_node_execution_id, iteration_no, available_at_utc
  ) VALUES (
    p_workflow_instance_id, p_action_workflow_node_id, 'READY', 1,
    p_parent_schedule_execution_id, p_iteration_no, p_available_at
  ) RETURNING id INTO v_ne_id;

  IF p_parent_schedule_execution_id IS NOT NULL THEN
    SELECT wn.node_type INTO v_parent_ntype
    FROM wf.node_execution ne
    INNER JOIN wf.workflow_node wn ON wn.id = ne.workflow_node_id
    WHERE ne.id = p_parent_schedule_execution_id;
    IF v_parent_ntype IN ('PARALLEL', 'FOREACH') THEN
      INSERT INTO wf.scope_variable (workflow_instance_id, scope_node_execution_id, var_name, value_json)
      SELECT sv.workflow_instance_id, v_ne_id, sv.var_name, sv.value_json
      FROM wf.scope_variable sv
      WHERE sv.workflow_instance_id = p_workflow_instance_id
        AND sv.scope_node_execution_id = p_parent_schedule_execution_id;
    END IF;
  END IF;

  CALL wf.wf_seed_execution_context(
    v_ne_id, p_workflow_instance_id, p_action_workflow_node_id,
    p_parent_schedule_execution_id, p_iteration_no, NULL, NULL
  );

  SELECT * INTO v_fj, v_failed, v_fc, v_fm
  FROM wf.wf_build_input_json_for_action(v_ne_id, p_workflow_instance_id, p_action_workflow_node_id);

  IF v_failed THEN
    UPDATE wf.node_execution SET status = 'FAILED', engine_error_code = v_fc, engine_error_message = v_fm,
      ended_at_utc = (now() AT TIME ZONE 'utc') WHERE id = v_ne_id;
    UPDATE wf.workflow_instance SET status = 'FAILED', completed_at_utc = (now() AT TIME ZONE 'utc')
    WHERE id = p_workflow_instance_id AND status = 'RUNNING';
    RETURN;
  END IF;

  UPDATE wf.node_execution SET input_json = v_fj WHERE id = v_ne_id;
  CALL wf.wf_stamp_affinity_key(v_ne_id, p_action_workflow_node_id, v_fj);
END;
$$;

-- Remove legacy single-argument overload so CALL with one argument is not ambiguous
-- against (bigint, boolean) when the second parameter has a default.
DROP PROCEDURE IF EXISTS wf.wf_schedule_continue(bigint);

CREATE OR REPLACE PROCEDURE wf.wf_schedule_continue(
  IN p_schedule_execution_id bigint,
  IN p_delay_first boolean DEFAULT false
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_inst bigint;
  v_schedule_node bigint;
  v_interval int;
  v_child bigint;
  v_now timestamptz;
  v_avail timestamptz;
BEGIN
  SELECT ne.workflow_instance_id, ne.workflow_node_id INTO v_inst, v_schedule_node
  FROM wf.node_execution ne WHERE ne.id = p_schedule_execution_id;

  IF NOT EXISTS (
    SELECT 1 FROM wf.workflow_instance wi
    WHERE wi.id = v_inst AND wi.status = 'RUNNING'
  ) THEN
    RETURN;
  END IF;

  SELECT greatest(coalesce(wn.schedule_interval_seconds, 60), 1) INTO v_interval
  FROM wf.workflow_node wn WHERE wn.id = v_schedule_node;

  SELECT e.child_node_id INTO v_child
  FROM wf.workflow_edge e
  WHERE e.parent_node_id = v_schedule_node
  ORDER BY e.child_order ASC
  LIMIT 1;

  IF v_child IS NULL THEN
    UPDATE wf.node_execution
    SET status = 'FAILED', engine_error_code = 10021,
        engine_error_message = 'SCHEDULE node has no child action.',
        ended_at_utc = (now() AT TIME ZONE 'utc')
    WHERE id = p_schedule_execution_id;
    UPDATE wf.workflow_instance
    SET status = 'FAILED', completed_at_utc = (now() AT TIME ZONE 'utc')
    WHERE id = v_inst AND status = 'RUNNING';
    RETURN;
  END IF;

  v_now := (now() AT TIME ZONE 'utc');
  IF p_delay_first THEN
    v_avail := v_now + make_interval(secs => v_interval);
  ELSE
    v_avail := v_now;
  END IF;

  CALL wf.wf_engine_enqueue_scheduled_action(
    v_inst, v_child, p_schedule_execution_id, 1, v_avail
  );
END;
$$;
