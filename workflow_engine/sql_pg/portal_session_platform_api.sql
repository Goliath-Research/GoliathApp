/*
  Session-gated wrappers for portal operator list/read surfaces (platform BFF).
  Callable by goliath_portal only — validates session + active scope before delegating
  to existing portal.sp_* catalog procs or semantic tables.
*/

CREATE OR REPLACE FUNCTION portal.fn_session_operator_require(
  p_session_token text,
  p_node_path text DEFAULT NULL
)
RETURNS TABLE (
  session_id integer,
  user_id integer,
  active_scope_id integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
BEGIN
  SELECT *
  INTO v_sess
  FROM portal.fn_session_resolve(p_session_token)
  LIMIT 1;

  IF v_sess.session_id IS NULL OR COALESCE(v_sess.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;

  IF v_sess.active_scope_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'session active scope required');
  END IF;

  IF p_node_path IS NOT NULL AND btrim(p_node_path) <> '' THEN
    IF NOT EXISTS (
      SELECT 1
      FROM portal.sp_session_operator_nav_tree(p_session_token) nt
      WHERE nt.node_path = p_node_path
    ) THEN
      PERFORM portal.fn_semantic_raise('GS403', 'operator nav entitlement denied');
    END IF;
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_users(
  p_session_token text,
  p_include_inactive boolean DEFAULT false
)
RETURNS TABLE (
  user_id int,
  full_name text,
  email text,
  active int
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/admin/users');
  RETURN QUERY SELECT * FROM portal.sp_list_users(p_include_inactive);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_roles(p_session_token text)
RETURNS TABLE (
  role_id int,
  name text,
  bypass_scope boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/admin/roles');
  RETURN QUERY SELECT * FROM portal.sp_list_roles();
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_permissions(
  p_session_token text,
  p_role_id int DEFAULT NULL
)
RETURNS TABLE (
  permission_id int,
  name text,
  obj_id int,
  operation_id int,
  role_id int
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/admin/permissions');
  RETURN QUERY SELECT * FROM portal.sp_list_permissions(p_role_id);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_scopes(
  p_session_token text,
  p_include_inactive boolean DEFAULT false
)
RETURNS TABLE (
  scope_id int,
  scope_type text,
  name text,
  organization_id int,
  owner_user_id int,
  active boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/admin/scopes');
  RETURN QUERY SELECT * FROM portal.sp_list_scopes(p_include_inactive);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_invitations(
  p_session_token text,
  p_scope_id int DEFAULT NULL,
  p_status text DEFAULT NULL
)
RETURNS TABLE (
  invitation_id bigint,
  batch_id bigint,
  scope_id int,
  email text,
  default_role_id int,
  grant_type text,
  status text,
  expires_at_utc timestamptz,
  accepted_by_user_id int,
  accepted_at_utc timestamptz,
  created_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", "Onboarding", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/admin/invitations');
  RETURN QUERY SELECT * FROM portal.sp_list_invitations(p_scope_id, p_status);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_workflow_defs(
  p_session_token text,
  p_source_filter text DEFAULT NULL
)
RETURNS TABLE (
  workflow_def_id bigint,
  name text,
  source text,
  active_version_id bigint,
  version_major int,
  version_minor int
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/definitions');
  RETURN QUERY SELECT * FROM portal.sp_list_workflow_defs(p_source_filter);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_workflow_actions(p_session_token text)
RETURNS TABLE (
  id bigint,
  action_name text,
  capability text,
  execution_mode text,
  cli_tool text,
  in_process_handler text,
  implementation_status text,
  can_pause boolean,
  can_continue boolean,
  can_stop boolean,
  input_type_id bigint,
  input_type_name text,
  output_type_id bigint,
  output_type_name text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/actions');
  RETURN QUERY SELECT * FROM portal.sp_list_workflow_actions();
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_recent_instances(
  p_session_token text,
  p_hours_back int DEFAULT 168,
  p_limit int DEFAULT 100
)
RETURNS TABLE (
  instance_id bigint,
  workflow_def_name text,
  status text,
  study_name text,
  started_at_utc timestamptz,
  completed_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, cfg, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/runs');
  RETURN QUERY SELECT * FROM portal.sp_list_recent_instances(p_hours_back, p_limit);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_domain_programs(
  p_session_token text,
  p_published_only boolean DEFAULT false
)
RETURNS TABLE (
  id bigint,
  name text,
  version text,
  status text,
  content_hash text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/domain-programs');
  RETURN QUERY SELECT * FROM portal.sp_list_domain_programs(p_published_only);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_worker_enrollments(
  p_session_token text,
  p_cluster_key text DEFAULT NULL
)
RETURNS TABLE (
  id bigint,
  cluster_key text,
  public_ip text,
  external_worker_key text,
  status varchar,
  enrolled_worker_id bigint,
  enrolled_at_utc timestamptz,
  created_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/workers');
  RETURN QUERY SELECT * FROM portal.sp_list_worker_enrollments(p_cluster_key);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_worker_health(
  p_session_token text,
  p_cluster_key text DEFAULT NULL
)
RETURNS TABLE (
  worker_id bigint,
  cluster_id bigint,
  cluster_key text,
  external_worker_key text,
  display_name text,
  hostname text,
  status text,
  desired_state text,
  capabilities jsonb,
  last_seen_at_utc timestamptz,
  created_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/operations/worker-fleet');
  RETURN QUERY SELECT * FROM portal.sp_list_worker_health(p_cluster_key);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_pipeline_profiles(
  p_session_token text,
  p_published_only boolean DEFAULT false
)
RETURNS TABLE (
  id bigint,
  name text,
  version text,
  status text,
  content_hash text,
  document_json jsonb,
  created_at_utc timestamptz,
  updated_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/config/pipeline-profiles');
  RETURN QUERY SELECT * FROM portal.sp_list_pipeline_profiles(p_published_only);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_sites(p_session_token text)
RETURNS TABLE (
  id bigint,
  name text,
  version text,
  status text,
  content_hash text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/config/site');
  RETURN QUERY SELECT * FROM portal.sp_list_sites(false);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_workflow_versions(
  p_session_token text,
  p_workflow_def_id bigint DEFAULT NULL
)
RETURNS TABLE (
  workflow_version_id bigint,
  workflow_def_id bigint,
  workflow_def_name text,
  version_major int,
  version_minor int,
  is_active boolean,
  root_node_id bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/definitions');
  RETURN QUERY SELECT * FROM portal.sp_list_workflow_versions(p_workflow_def_id, NULL);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_workflow_step_nodes(p_session_token text)
RETURNS TABLE (
  workflow_def_name text,
  version_major int,
  version_minor int,
  node_key text,
  node_type text,
  action_name text,
  capability text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/steps');
  RETURN QUERY
  SELECT
    wd.name,
    wv.version_major,
    wv.version_minor,
    wn.node_key,
    wn.node_type::text,
    wa.action_name,
    wa.capability
  FROM wf.workflow_node wn
  JOIN wf.workflow_version wv ON wv.id = wn.workflow_version_id
  JOIN wf.workflow_def wd ON wd.id = wv.workflow_def_id
  LEFT JOIN wf.workflow_action wa ON wa.id = wn.workflow_action_id
  WHERE wv.is_active
  ORDER BY wd.name, wn.node_key;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_schedule_nodes(p_session_token text)
RETURNS TABLE (
  workflow_def_name text,
  node_key text,
  schedule_interval_seconds int
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/operations/schedules');
  RETURN QUERY
  SELECT wd.name, wn.node_key, wn.schedule_interval_seconds
  FROM wf.workflow_node wn
  JOIN wf.workflow_version wv ON wv.id = wn.workflow_version_id AND wv.is_active
  JOIN wf.workflow_def wd ON wd.id = wv.workflow_def_id
  WHERE wn.node_type = 'SCHEDULE'
  ORDER BY wd.name, wn.node_key;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_data_types(
  p_session_token text,
  p_published_only boolean DEFAULT true
)
RETURNS TABLE (
  id bigint,
  name text,
  version text,
  status text,
  kind text,
  element_type_id bigint,
  element_type_name text,
  content_hash text,
  created_at_utc timestamptz,
  updated_at_utc timestamptz,
  field_count bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/meta/data-types');
  RETURN QUERY SELECT * FROM portal.sp_list_data_types(p_published_only);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_semantic_namespaces(p_session_token text)
RETURNS TABLE (
  code text,
  display_name text,
  owner_app text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/semantic/namespaces');
  RETURN QUERY
  SELECT n.code, n.display_name, n.owner_app
  FROM portal.semantic_namespace n
  ORDER BY n.code;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_semantic_entities(p_session_token text)
RETURNS TABLE (
  id integer,
  namespace text,
  code text,
  display_name text,
  schema_version text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/semantic/entities');
  RETURN QUERY
  SELECT e.id, e.namespace, e.code, e.display_name, e.schema_version
  FROM portal.semantic_entity e
  ORDER BY e.namespace, e.code;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_semantic_attributes(
  p_session_token text,
  p_entity_id int DEFAULT NULL
)
RETURNS TABLE (
  id integer,
  entity_id integer,
  code text,
  column_name text,
  json_type text,
  role text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/semantic/attributes');
  RETURN QUERY
  SELECT a.id, a.entity_id, a.code, a.column_name, a.json_type, a.role::text
  FROM portal.semantic_attribute a
  WHERE p_entity_id IS NULL OR a.entity_id = p_entity_id
  ORDER BY a.entity_id, a.code;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_semantic_requests(p_session_token text)
RETURNS TABLE (
  request_code text,
  version text,
  namespace text,
  entity_code text,
  display_name text,
  required_permission text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_user_id integer;
BEGIN
  SELECT user_id INTO v_user_id
  FROM portal.fn_session_operator_require(p_session_token, '/app/semantic/requests')
  LIMIT 1;

  RETURN QUERY
  SELECT
    r.request_code,
    r.version,
    r.namespace,
    e.code,
    e.display_name,
    r.required_permission
  FROM portal.semantic_request r
  INNER JOIN portal.semantic_entity e ON e.id = r.entity_id
  WHERE r.required_permission IS NULL
     OR portal.fn_semantic_session_has_permission(v_user_id, r.required_permission)
  ORDER BY r.namespace, r.request_code, r.version;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_event_types(p_session_token text)
RETURNS TABLE (
  event_type_id bigint,
  name text,
  created_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/operations/events');
  RETURN QUERY
  SELECT et.id, et.name, et.created_at_utc
  FROM wf.event_type et
  ORDER BY et.name;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_event_subscriptions(p_session_token text)
RETURNS TABLE (
  subscription_id bigint,
  event_type_name text,
  workflow_def_name text,
  version_major int,
  version_minor int,
  mode text,
  enabled boolean,
  created_at_utc timestamptz
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/subscriptions');
  RETURN QUERY
  SELECT
    s.id,
    et.name,
    wd.name,
    wv.version_major,
    wv.version_minor,
    s.mode::text,
    s.enabled,
    s.created_at_utc
  FROM wf.event_subscription s
  JOIN wf.event_type et ON et.id = s.event_type_id
  JOIN wf.workflow_version wv ON wv.id = s.workflow_version_id
  JOIN wf.workflow_def wd ON wd.id = wv.workflow_def_id
  ORDER BY s.id DESC;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_recent_events(
  p_session_token text,
  p_limit int DEFAULT 100
)
RETURNS TABLE (
  event_id bigint,
  event_type_name text,
  occurred_at_utc timestamptz,
  source text,
  correlation_key text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/operations/events');
  RETURN QUERY
  SELECT ev.id, et.name, ev.occurred_at_utc, ev.source, ev.correlation_key
  FROM wf.event ev
  JOIN wf.event_type et ON et.id = ev.event_type_id
  ORDER BY ev.ingested_at_utc DESC
  LIMIT GREATEST(1, LEAST(p_limit, 500));
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_semantic_entities_enriched(p_session_token text)
RETURNS TABLE (
  id integer,
  namespace text,
  code text,
  display_name text,
  schema_version text,
  meta_class_name text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/semantic/entities');
  RETURN QUERY
  SELECT
    e.id,
    e.namespace,
    e.code,
    e.display_name,
    e.schema_version,
    c."Name"::text AS meta_class_name
  FROM portal.semantic_entity e
  LEFT JOIN "Meta"."Classes" c ON c."ID" = e.meta_class_id
  ORDER BY e.namespace, e.code;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_list_classes(p_session_token text)
RETURNS TABLE (
  class_id integer,
  class_name text,
  parent_id integer,
  is_abstract boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_meta_require(p_session_token, 'meta.schema.read');
  RETURN QUERY
  SELECT c."ID"::integer, c."Name"::text, c."ParentID"::integer, COALESCE(c."IsAbstract", false)
  FROM "Meta"."Classes" c
  ORDER BY c."Name";
END;
$$;
