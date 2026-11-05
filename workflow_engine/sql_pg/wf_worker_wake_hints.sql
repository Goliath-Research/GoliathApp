/*
  Claimable-task wake hint collection for dual worker activation (tier 1).

  Returns distinct pool / capability / program_id / workflow_instance_id tuples for
  READY ACTION nodes on RUNNING instances. Used by the gateway wake publisher after
  event ingest, workflow instance start, and lease reclaim (non-quiet).
*/

CREATE OR REPLACE FUNCTION wf.fn_worker_wake_hints_for_instances(
  p_instance_ids bigint[]
)
RETURNS TABLE (
  pool text,
  capability text,
  program_id text,
  workflow_instance_id bigint
)
LANGUAGE sql
STABLE
AS $$
  WITH inst AS (
    SELECT DISTINCT unnest(p_instance_ids) AS workflow_instance_id
  ),
  programs AS (
    SELECT
      wi.id AS workflow_instance_id,
      COALESCE(
        dp_link.name || '@' || dp_link.version,
        dp_pub.name || '@' || dp_pub.version
      ) AS program_id
    FROM inst
    INNER JOIN wf.workflow_instance wi ON wi.id = inst.workflow_instance_id
    LEFT JOIN cfg.study_instance_link sil ON sil.workflow_instance_id = wi.id
    LEFT JOIN cfg.domain_program dp_link ON dp_link.id = sil.domain_program_id
    LEFT JOIN cfg.program_publish pp ON pp.workflow_version_id = wi.workflow_version_id
    LEFT JOIN cfg.domain_program dp_pub ON dp_pub.id = pp.domain_program_id
  )
  SELECT DISTINCT
    NULLIF(btrim(wi.context_json ->> 'pool'), '') AS pool,
    NULLIF(btrim(wa.capability), '') AS capability,
    NULLIF(btrim(p.program_id), '') AS program_id,
    ne.workflow_instance_id
  FROM inst
  INNER JOIN wf.node_execution ne ON ne.workflow_instance_id = inst.workflow_instance_id
  INNER JOIN wf.workflow_node wn ON wn.id = ne.workflow_node_id
  INNER JOIN wf.workflow_action wa ON wa.id = wn.workflow_action_id
  INNER JOIN wf.workflow_instance wi ON wi.id = ne.workflow_instance_id
  LEFT JOIN programs p ON p.workflow_instance_id = wi.id
  WHERE ne.status = 'READY'
    AND wn.node_type = 'ACTION'
    AND wi.status = 'RUNNING'
    AND (ne.available_at_utc IS NULL OR ne.available_at_utc <= (now() AT TIME ZONE 'utc'))
    AND (
      NULLIF(btrim(wa.capability), '') IS NOT NULL
      OR NULLIF(btrim(p.program_id), '') IS NOT NULL
      OR NULLIF(btrim(wi.context_json ->> 'pool'), '') IS NOT NULL
    );
$$;

CREATE OR REPLACE FUNCTION wf.fn_worker_wake_hints_for_event(
  p_event_id bigint
)
RETURNS TABLE (
  pool text,
  capability text,
  program_id text,
  workflow_instance_id bigint
)
LANGUAGE sql
STABLE
AS $$
  WITH touched AS (
    SELECT DISTINCT ed.workflow_instance_id
    FROM wf.event_delivery ed
    WHERE ed.event_id = p_event_id
      AND ed.status = 'applied'
      AND ed.workflow_instance_id IS NOT NULL
  )
  SELECT h.pool, h.capability, h.program_id, h.workflow_instance_id
  FROM touched t
  CROSS JOIN LATERAL wf.fn_worker_wake_hints_for_instances(ARRAY[t.workflow_instance_id]) AS h;
$$;

CREATE OR REPLACE FUNCTION wf.fn_worker_wake_hints_for_node_executions(
  p_node_execution_ids bigint[]
)
RETURNS TABLE (
  pool text,
  capability text,
  program_id text,
  workflow_instance_id bigint
)
LANGUAGE sql
STABLE
AS $$
  WITH nodes AS (
    SELECT DISTINCT ne.workflow_instance_id
    FROM wf.node_execution ne
    WHERE ne.id = ANY (p_node_execution_ids)
  )
  SELECT h.pool, h.capability, h.program_id, h.workflow_instance_id
  FROM nodes n
  CROSS JOIN LATERAL wf.fn_worker_wake_hints_for_instances(ARRAY[n.workflow_instance_id]) AS h;
$$;
