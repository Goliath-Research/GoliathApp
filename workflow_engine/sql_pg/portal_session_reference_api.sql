/*
  Reference picker search for the platform host property grid (`x-goliath-ref` hint).
  Callable by goliath_portal only. Each kind requires the session to hold at least one of
  the operator NavTree entitlements that edit or read that catalog. Read-only.
*/

CREATE OR REPLACE FUNCTION portal.fn_session_require_any_nav(
  p_session_token text,
  p_node_paths text[]
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, NULL);
  IF NOT EXISTS (
    SELECT 1
    FROM portal.sp_session_operator_nav_tree(p_session_token) nt
    WHERE nt.node_path = ANY (p_node_paths)
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'operator nav entitlement denied');
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_search_references(
  p_session_token text,
  p_kind text,
  p_query text DEFAULT '',
  p_limit int DEFAULT 50
)
RETURNS TABLE (
  ref_value text,
  label text,
  detail text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, cfg, "Meta", pg_temp
AS $$
DECLARE
  v_kind text := lower(btrim(coalesce(p_kind, '')));
  v_q text := '%' || replace(replace(replace(btrim(coalesce(p_query, '')), '\', '\\'), '%', '\%'), '_', '\_') || '%';
  v_limit int := GREATEST(1, LEAST(coalesce(p_limit, 50), 200));
BEGIN
  IF v_kind IN ('action', 'meta_method') THEN
    PERFORM portal.fn_session_require_any_nav(
      p_session_token,
      ARRAY['/app/workflows/actions', '/app/meta/methods', '/app/workflows/definitions', '/app/workflows/steps']
    );
  ELSIF v_kind IN ('workflow_def', 'workflow_version') THEN
    PERFORM portal.fn_session_require_any_nav(
      p_session_token,
      ARRAY['/app/workflows/definitions', '/app/workflows/steps', '/app/workflows/subscriptions',
            '/app/workflows/runs', '/app/workflows/domain-programs']
    );
  ELSIF v_kind = 'event_type' THEN
    PERFORM portal.fn_session_require_any_nav(
      p_session_token,
      ARRAY['/app/workflows/subscriptions', '/app/operations/events']
    );
  ELSIF v_kind IN ('cluster', 'worker') THEN
    PERFORM portal.fn_session_require_any_nav(
      p_session_token,
      ARRAY['/app/workflows/workers', '/app/operations/worker-fleet']
    );
  ELSIF v_kind IN ('data_type', 'meta_class') THEN
    PERFORM portal.fn_session_require_any_nav(
      p_session_token,
      ARRAY['/app/meta', '/app/meta/classes', '/app/meta/data-types', '/app/meta/methods',
            '/app/workflows/actions']
    );
  ELSIF v_kind = 'study' THEN
    PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/workflows/runs']);
  ELSE
    PERFORM portal.fn_semantic_raise('GS400', format('unknown reference kind %s', coalesce(p_kind, '')));
  END IF;

  IF v_kind = 'action' THEN
    RETURN QUERY
    SELECT a.action_name, a.action_name,
           concat_ws(' · ', a.namespace, a.capability, a.implementation_status)
    FROM wf.workflow_action a
    WHERE a.action_name ILIKE v_q OR coalesce(a.capability, '') ILIKE v_q
    ORDER BY a.action_name
    LIMIT v_limit;
  ELSIF v_kind = 'meta_method' THEN
    RETURN QUERY
    SELECT m."ID"::text, c."Name" || '.' || m."Name",
           concat_ws(' · ', m."ImplKind", m."ImplRef")
    FROM "Meta"."Methods" m
    JOIN "Meta"."Classes" c ON c."ID" = m."ClassID"
    WHERE c."Name" ILIKE v_q OR m."Name" ILIKE v_q OR coalesce(m."ImplRef", '') ILIKE v_q
    ORDER BY c."Name", m."Name"
    LIMIT v_limit;
  ELSIF v_kind = 'workflow_def' THEN
    RETURN QUERY
    SELECT d.id::text, d.name, d.description
    FROM wf.workflow_def d
    WHERE d.name ILIKE v_q
    ORDER BY d.name
    LIMIT v_limit;
  ELSIF v_kind = 'workflow_version' THEN
    RETURN QUERY
    SELECT v.id::text,
           format('%s v%s.%s', d.name, v.version_major, v.version_minor),
           CASE WHEN v.is_active THEN 'active' ELSE 'inactive' END
    FROM wf.workflow_version v
    JOIN wf.workflow_def d ON d.id = v.workflow_def_id
    WHERE d.name ILIKE v_q
    ORDER BY d.name, v.version_major DESC, v.version_minor DESC
    LIMIT v_limit;
  ELSIF v_kind = 'event_type' THEN
    RETURN QUERY
    SELECT et.name, et.name, NULL::text
    FROM wf.event_type et
    WHERE et.name ILIKE v_q
    ORDER BY et.name
    LIMIT v_limit;
  ELSIF v_kind = 'cluster' THEN
    RETURN QUERY
    SELECT c.id::text, c.name, concat_ws(' · ', c.cluster_key, c.provider, c.status)
    FROM wf.cluster c
    WHERE c.cluster_key ILIKE v_q OR c.name ILIKE v_q
    ORDER BY c.name
    LIMIT v_limit;
  ELSIF v_kind = 'worker' THEN
    RETURN QUERY
    SELECT w.id::text, coalesce(w.display_name, w.external_worker_key, w.id::text),
           concat_ws(' · ', c.cluster_key, w.status, w.desired_state)
    FROM wf.worker w
    JOIN wf.cluster c ON c.id = w.cluster_id
    WHERE coalesce(w.display_name, '') ILIKE v_q OR coalesce(w.external_worker_key, '') ILIKE v_q
       OR coalesce(w.hostname, '') ILIKE v_q
    ORDER BY 2
    LIMIT v_limit;
  ELSIF v_kind = 'data_type' THEN
    RETURN QUERY
    SELECT t.id::text, t.name || '@' || t.version,
           concat_ws(' · ', t.kind, t.status, cl."Name")
    FROM wf.data_type t
    LEFT JOIN "Meta"."Classes" cl ON cl."ID" = t.class_id
    WHERE (t.name ILIKE v_q OR coalesce(t.description, '') ILIKE v_q)
      AND t.status <> 'retired'
    ORDER BY t.name, t.version DESC
    LIMIT v_limit;
  ELSIF v_kind = 'meta_class' THEN
    RETURN QUERY
    SELECT c."Name"::text, c."Name"::text,
           CASE WHEN coalesce(c."IsAbstract", false) THEN 'abstract' ELSE NULL END
    FROM "Meta"."Classes" c
    WHERE c."Name" ILIKE v_q
    ORDER BY c."Name"
    LIMIT v_limit;
  ELSIF v_kind = 'study' THEN
    RETURN QUERY
    SELECT s.id::text, s.name, concat_ws(' · ', 'v' || s.version, s.status)
    FROM cfg.study s
    WHERE s.name ILIKE v_q OR coalesce(s.study_id, '') ILIKE v_q
    ORDER BY s.name, s.version DESC
    LIMIT v_limit;
  END IF;
END;
$$;
