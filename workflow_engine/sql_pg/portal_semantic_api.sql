/*
  Semantic registry registration, runner, filter compiler, and validator (A2).
  Prerequisites: portal_semantic_schema.sql, portal_semantic_row_types.sql, portal_session_api.sql
*/

CREATE OR REPLACE FUNCTION portal.fn_semantic_max_rows()
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
  SELECT cfg.fn_portal_auth_int('semantic_max_rows', 500);
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_user_organization_ids(p_user_id integer)
RETURNS integer[]
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  SELECT COALESCE(array_agg(m."OrganizationID" ORDER BY m."OrganizationID"), '{}'::integer[])
  FROM portal."OrganizationMembers" m
  WHERE m."UserID" = p_user_id;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_session_has_permission(
  p_user_id integer,
  p_permission text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT
    p_permission IS NULL
    OR EXISTS (
      SELECT 1
      FROM "RBAC"."UserRoleGrants" g
      INNER JOIN "RBAC"."Role_Permissions" rp ON rp."RoleID" = g."RoleID"
      INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
      WHERE g."UserID" = p_user_id
        AND g."Active"
        AND p."Name" = p_permission
    );
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_validate_params(
  p_request_code text,
  p_schema jsonb,
  p_params jsonb
)
RETURNS void
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_key text;
  v_required jsonb;
  v_props jsonb;
  v_type text;
  v_val jsonb;
BEGIN
  IF p_schema IS NULL OR p_schema = '{}'::jsonb THEN
    RETURN;
  END IF;

  IF COALESCE(p_schema->>'type', 'object') <> 'object' THEN
    PERFORM portal.fn_semantic_raise(
      'GS400',
      format('semantic params schema must be object for %s', p_request_code)
    );
  END IF;

  v_required := COALESCE(p_schema->'required', '[]'::jsonb);
  IF jsonb_typeof(v_required) = 'array' THEN
    FOR v_key IN
      SELECT jsonb_array_elements_text(v_required)
    LOOP
      IF p_params ? v_key IS FALSE OR p_params->v_key = 'null'::jsonb THEN
        PERFORM portal.fn_semantic_raise(
          'GS400',
          format('missing required param %s for %s', v_key, p_request_code)
        );
      END IF;
    END LOOP;
  END IF;

  v_props := COALESCE(p_schema->'properties', '{}'::jsonb);
  FOR v_key, v_val IN SELECT * FROM jsonb_each(p_params)
  LOOP
    IF NOT (v_props ? v_key) THEN
      IF COALESCE((p_schema->>'additionalProperties')::boolean, true) = false THEN
        PERFORM portal.fn_semantic_raise(
          'GS400',
          format('unknown param %s for %s', v_key, p_request_code)
        );
      END IF;
      CONTINUE;
    END IF;
    v_type := v_props->v_key->>'type';
    IF v_type = 'integer' AND jsonb_typeof(v_val) <> 'number' THEN
      PERFORM portal.fn_semantic_raise(
        'GS400',
        format('param %s must be integer for %s', v_key, p_request_code)
      );
    ELSIF v_type = 'string' AND jsonb_typeof(v_val) <> 'string' THEN
      PERFORM portal.fn_semantic_raise(
        'GS400',
        format('param %s must be string for %s', v_key, p_request_code)
      );
    ELSIF v_type = 'boolean' AND jsonb_typeof(v_val) <> 'boolean' THEN
      PERFORM portal.fn_semantic_raise(
        'GS400',
        format('param %s must be boolean for %s', v_key, p_request_code)
      );
    END IF;
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_compile_filter(
  p_entity_id integer,
  p_filter jsonb,
  p_params jsonb,
  p_placeholder_start integer DEFAULT 1,
  OUT where_sql text,
  OUT arg_values text[]
)
RETURNS record
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_pred jsonb;
  v_attr text;
  v_op text;
  v_param text;
  v_col text;
  v_ops text[];
  v_val jsonb;
  v_parts text[] := ARRAY[]::text[];
  v_args text[] := ARRAY[]::text[];
  v_idx int := GREATEST(1, COALESCE(p_placeholder_start, 1)) - 1;
BEGIN
  where_sql := 'TRUE';
  arg_values := ARRAY[]::text[];

  IF p_filter IS NULL OR p_filter = 'null'::jsonb OR p_filter = '{}'::jsonb THEN
    RETURN;
  END IF;

  IF p_filter ? 'any_of' OR p_filter ? 'one_of' OR p_filter ? 'not' THEN
    PERFORM portal.fn_semantic_raise(
      'GS501',
      'filter_template.any_of is not supported in v1'
    );
  END IF;

  IF NOT (p_filter ? 'all_of') THEN
    PERFORM portal.fn_semantic_raise(
      'GS501',
      'filter_template must use all_of in v1'
    );
  END IF;

  FOR v_pred IN SELECT * FROM jsonb_array_elements(COALESCE(p_filter->'all_of', '[]'::jsonb))
  LOOP
    v_attr := v_pred->>'attribute';
    v_op := v_pred->>'op';
    v_param := v_pred->>'param';

    IF v_attr IS NULL OR v_op IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS501', 'filter predicate requires attribute and op');
    END IF;

    SELECT a.column_name, a.filterable_ops
    INTO v_col, v_ops
    FROM portal.semantic_attribute a
    WHERE a.entity_id = p_entity_id
      AND a.code = v_attr
      AND a.role IN ('filter', 'list', 'detail');

    IF v_col IS NULL THEN
      PERFORM portal.fn_semantic_raise(
        'GS501',
        format('filter attribute %s is not filterable', v_attr)
      );
    END IF;

    IF NOT (v_op = ANY (v_ops)) THEN
      PERFORM portal.fn_semantic_raise(
        'GS501',
        format('filter op %s is not allowed on %s', v_op, v_attr)
      );
    END IF;

    IF v_op = 'is_null' THEN
      v_parts := array_append(v_parts, format('%I IS NULL', v_col));
      CONTINUE;
    END IF;

    IF v_param IS NULL OR NOT (p_params ? v_param) THEN
      PERFORM portal.fn_semantic_raise(
        'GS400',
        format('filter param %s is required', COALESCE(v_param, '<missing>'))
      );
    END IF;

    v_val := p_params->v_param;

    CASE v_op
      WHEN 'eq' THEN
        v_idx := v_idx + 1;
        v_args := array_append(v_args, v_val #>> '{}');
        v_parts := array_append(v_parts, format('%I::text = $%s', v_col, v_idx));
      WHEN 'gte' THEN
        v_idx := v_idx + 1;
        v_args := array_append(v_args, v_val #>> '{}');
        v_parts := array_append(v_parts, format('%I::text >= $%s', v_col, v_idx));
      WHEN 'lte' THEN
        v_idx := v_idx + 1;
        v_args := array_append(v_args, v_val #>> '{}');
        v_parts := array_append(v_parts, format('%I::text <= $%s', v_col, v_idx));
      WHEN 'starts_with' THEN
        v_idx := v_idx + 1;
        v_args := array_append(v_args, v_val #>> '{}');
        v_parts := array_append(v_parts, format('%I ILIKE ($%s || ''%%'')', v_col, v_idx));
      WHEN 'in' THEN
        PERFORM portal.fn_semantic_raise('GS501', 'filter op in is not supported in v1');
      WHEN 'between' THEN
        PERFORM portal.fn_semantic_raise('GS501', 'filter op between is not supported in v1');
      ELSE
        PERFORM portal.fn_semantic_raise(
          'GS501',
          format('filter op %s is not supported in v1', v_op)
        );
    END CASE;
  END LOOP;

  IF array_length(v_parts, 1) IS NOT NULL THEN
    where_sql := array_to_string(v_parts, ' AND ');
  END IF;
  arg_values := v_args;
END;
$$;

CREATE OR REPLACE PROCEDURE portal.sp_semantic_register_entity(
  IN p_namespace text,
  IN p_code text,
  IN p_display_name text,
  IN p_description text,
  IN p_schema_id text,
  IN p_schema_version text,
  IN p_content_hash text,
  IN p_storage_relation text DEFAULT NULL,
  IN p_meta_class_id integer DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO portal.semantic_namespace (code, display_name)
  VALUES (p_namespace, p_namespace)
  ON CONFLICT (code) DO NOTHING;

  INSERT INTO portal.semantic_entity (
    namespace, code, display_name, description, meta_class_id,
    storage_relation, schema_id, schema_version, content_hash
  )
  VALUES (
    p_namespace,
    p_code,
    p_display_name,
    COALESCE(p_description, ''),
    p_meta_class_id,
    p_storage_relation,
    p_schema_id,
    COALESCE(p_schema_version, '1'),
    COALESCE(p_content_hash, '')
  )
  ON CONFLICT (namespace, code) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    meta_class_id = EXCLUDED.meta_class_id,
    storage_relation = EXCLUDED.storage_relation,
    schema_id = EXCLUDED.schema_id,
    schema_version = EXCLUDED.schema_version,
    content_hash = EXCLUDED.content_hash;
END;
$$;

CREATE OR REPLACE PROCEDURE portal.sp_semantic_register_attribute(
  IN p_entity_id integer,
  IN p_code text,
  IN p_column_name text,
  IN p_json_type text,
  IN p_role text,
  IN p_filterable_ops text[]
)
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO portal.semantic_attribute (
    entity_id, code, column_name, json_type, role, filterable_ops
  )
  VALUES (
    p_entity_id, p_code, p_column_name, p_json_type, p_role, COALESCE(p_filterable_ops, '{}')
  )
  ON CONFLICT (entity_id, code) DO UPDATE SET
    column_name = EXCLUDED.column_name,
    json_type = EXCLUDED.json_type,
    role = EXCLUDED.role,
    filterable_ops = EXCLUDED.filterable_ops;
END;
$$;

CREATE OR REPLACE PROCEDURE portal.sp_semantic_register_request(
  IN p_request_code text,
  IN p_version text,
  IN p_namespace text,
  IN p_entity_id integer,
  IN p_target_kind text,
  IN p_target_name text,
  IN p_row_type text,
  IN p_params_schema jsonb,
  IN p_result_schema jsonb,
  IN p_content_hash text,
  IN p_filter_template jsonb DEFAULT NULL,
  IN p_required_permission text DEFAULT NULL,
  IN p_max_rows integer DEFAULT 500,
  IN p_base_namespace text DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_row_type regtype;
  v_type_name text := split_part(p_row_type, '.', 2);
BEGIN
  IF v_type_name = '' THEN
    v_type_name := p_row_type;
  END IF;

  SELECT t.oid::regtype
  INTO v_row_type
  FROM pg_type t
  INNER JOIN pg_namespace n ON n.oid = t.typnamespace
  WHERE n.nspname = 'portal'
    AND t.typname = v_type_name;

  IF v_row_type IS NULL THEN
    RAISE EXCEPTION 'semantic row type % not found in portal schema', p_row_type;
  END IF;
  INSERT INTO portal.semantic_namespace (code, display_name)
  VALUES (p_namespace, p_namespace)
  ON CONFLICT (code) DO NOTHING;

  INSERT INTO portal.semantic_request (
    request_code, version, namespace, base_namespace, entity_id,
    target_kind, target_name, row_type,
    params_schema, result_schema, filter_template,
    content_hash, required_permission, max_rows
  )
  VALUES (
    p_request_code,
    COALESCE(p_version, '1'),
    p_namespace,
    p_base_namespace,
    p_entity_id,
    p_target_kind,
    p_target_name,
    v_row_type,
    COALESCE(p_params_schema, '{}'::jsonb),
    COALESCE(p_result_schema, '{}'::jsonb),
    p_filter_template,
    COALESCE(p_content_hash, ''),
    p_required_permission,
    COALESCE(p_max_rows, 500)
  )
  ON CONFLICT (request_code, version) DO UPDATE SET
    namespace = EXCLUDED.namespace,
    base_namespace = EXCLUDED.base_namespace,
    entity_id = EXCLUDED.entity_id,
    target_kind = EXCLUDED.target_kind,
    target_name = EXCLUDED.target_name,
    row_type = EXCLUDED.row_type,
    params_schema = EXCLUDED.params_schema,
    result_schema = EXCLUDED.result_schema,
    filter_template = EXCLUDED.filter_template,
    content_hash = EXCLUDED.content_hash,
    required_permission = EXCLUDED.required_permission,
    max_rows = EXCLUDED.max_rows;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_core_list_organizations(
  p_user_id integer,
  p_params jsonb,
  p_limit integer
)
RETURNS SETOF portal.core_organization_row
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_org_filter integer;
BEGIN
  IF p_user_id IS NULL THEN
    RETURN;
  END IF;

  IF p_params ? 'organization_id' AND p_params->>'organization_id' IS NOT NULL THEN
    v_org_filter := (p_params->>'organization_id')::integer;
    IF NOT EXISTS (
      SELECT 1
      FROM portal."OrganizationMembers" m
      WHERE m."UserID" = p_user_id AND m."OrganizationID" = v_org_filter
    ) THEN
      PERFORM portal.fn_semantic_raise(
        'GS403',
        'organization scope denied'
      );
    END IF;
  END IF;

  RETURN QUERY
  SELECT
    o."ID",
    o."Name"::text,
    o."Active"
  FROM portal."Organizations" o
  INNER JOIN portal."OrganizationMembers" m ON m."OrganizationID" = o."ID"
  WHERE m."UserID" = p_user_id
    AND (
      v_org_filter IS NULL
      OR o."ID" = v_org_filter
    )
  ORDER BY o."Name"
  LIMIT GREATEST(0, COALESCE(p_limit, 500));
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_core_filter_organizations(
  p_user_id integer,
  p_params jsonb,
  p_limit integer,
  p_where_sql text,
  p_filter_args text[]
)
RETURNS SETOF portal.core_organization_row
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_sql text;
  v_org_ids integer[];
  v_lim integer;
BEGIN
  IF p_user_id IS NULL THEN
    RETURN;
  END IF;

  v_org_ids := portal.fn_semantic_user_organization_ids(p_user_id);
  IF COALESCE(array_length(v_org_ids, 1), 0) = 0 THEN
    RETURN;
  END IF;

  v_lim := GREATEST(0, COALESCE(p_limit, 500));
  v_sql := format(
    $q$
      SELECT o."ID", o."Name"::text, o."Active"
      FROM portal."Organizations" o
      WHERE o."ID" = ANY ($1)
        AND (%s)
      ORDER BY o."Name"
      LIMIT $2
    $q$,
    COALESCE(NULLIF(p_where_sql, ''), 'TRUE')
  );

  IF COALESCE(array_length(p_filter_args, 1), 0) = 0 THEN
    RETURN QUERY EXECUTE v_sql USING v_org_ids, v_lim;
  ELSIF array_length(p_filter_args, 1) = 1 THEN
    RETURN QUERY EXECUTE v_sql USING v_org_ids, v_lim, p_filter_args[1];
  ELSIF array_length(p_filter_args, 1) = 2 THEN
    RETURN QUERY EXECUTE v_sql USING v_org_ids, v_lim, p_filter_args[1], p_filter_args[2];
  ELSE
    PERFORM portal.fn_semantic_raise('GS501', 'too many filter parameters for v1');
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_run_semantic_request(
  p_session_token text,
  p_request_code text,
  p_version text DEFAULT '1',
  p_params jsonb DEFAULT '{}'::jsonb,
  p_filter jsonb DEFAULT NULL
)
RETURNS SETOF jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", cfg, pg_temp
AS $$
DECLARE
  v_sess record;
  v_req portal.semantic_request%ROWTYPE;
  v_limit integer;
  v_where text;
  v_args text[];
  v_sql text;
  v_entity portal.semantic_entity%ROWTYPE;
BEGIN
  SELECT *
  INTO v_sess
  FROM portal.fn_session_resolve(p_session_token)
  LIMIT 1;

  IF v_sess.session_id IS NULL OR v_sess.revoked THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;

  SELECT * INTO v_req
  FROM portal.semantic_request r
  WHERE r.request_code = p_request_code
    AND r.version = COALESCE(NULLIF(btrim(p_version), ''), '1');

  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise(
      'GS404',
      format('semantic request %s not found', p_request_code)
    );
  END IF;

  IF NOT portal.fn_semantic_session_has_permission(v_sess.user_id, v_req.required_permission) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'permission denied');
  END IF;

  PERFORM portal.fn_semantic_validate_params(p_request_code, v_req.params_schema, COALESCE(p_params, '{}'::jsonb));

  v_limit := LEAST(
    COALESCE((p_params->>'limit')::integer, v_req.max_rows),
    v_req.max_rows,
    portal.fn_semantic_max_rows()
  );
  IF v_limit IS NULL OR v_limit < 0 THEN
    v_limit := v_req.max_rows;
  END IF;

  SELECT * INTO v_entity FROM portal.semantic_entity e WHERE e.id = v_req.entity_id;

  IF v_req.target_kind = 'function' THEN
    IF p_filter IS NOT NULL AND p_filter <> '{}'::jsonb AND p_filter <> 'null'::jsonb THEN
      PERFORM portal.fn_semantic_raise(
        'GS501',
        'filter_template is not supported for function targets in v1'
      );
    END IF;
    RETURN QUERY EXECUTE format(
      'SELECT to_jsonb(r) FROM %s($1, $2, $3) r',
      v_req.target_name
    )
    USING v_sess.user_id, COALESCE(p_params, '{}'::jsonb), v_limit;
    RETURN;
  END IF;

  IF v_req.target_kind = 'template' THEN
    IF v_entity.storage_relation IS NULL OR btrim(v_entity.storage_relation) = '' THEN
      PERFORM portal.fn_semantic_raise('GS501', 'template target missing storage_relation');
    END IF;
    SELECT f.where_sql, f.arg_values
    INTO v_where, v_args
    FROM portal.fn_semantic_compile_filter(
      v_req.entity_id,
      COALESCE(p_filter, v_req.filter_template),
      p_params,
      3
    ) f;

    IF v_req.target_name = 'portal.fn_semantic_core_filter_organizations' THEN
      RETURN QUERY
      SELECT to_jsonb(r)
      FROM portal.fn_semantic_core_filter_organizations(
        v_sess.user_id,
        COALESCE(p_params, '{}'::jsonb),
        v_limit,
        v_where,
        v_args
      ) r;
      RETURN;
    END IF;

    PERFORM portal.fn_semantic_raise(
      'GS501',
      format('template target %s is not supported in v1', v_req.target_name)
    );
  END IF;

  PERFORM portal.fn_semantic_raise(
    'GS501',
    format('target_kind %s is not supported in v1', v_req.target_kind)
  );
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_list_semantic_catalog(p_session_token text)
RETURNS TABLE (
  request_code text,
  version text,
  namespace text,
  entity_code text,
  display_name text,
  params_schema jsonb,
  result_schema jsonb,
  required_permission text
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

  IF v_sess.session_id IS NULL OR v_sess.revoked THEN
    RETURN;
  END IF;

  RETURN QUERY
  SELECT
    r.request_code,
    r.version,
    r.namespace,
    e.code,
    e.display_name,
    r.params_schema,
    r.result_schema,
    r.required_permission
  FROM portal.semantic_request r
  INNER JOIN portal.semantic_entity e ON e.id = r.entity_id
  WHERE portal.fn_semantic_session_has_permission(v_sess.user_id, r.required_permission)
  ORDER BY r.namespace, r.request_code, r.version;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_validate_semantic_registry()
RETURNS TABLE (check_name text, ok boolean, detail text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
DECLARE
  v_rec record;
  v_fn regprocedure;
BEGIN
  RETURN QUERY SELECT 'semantic_namespace_seeded'::text, EXISTS (
    SELECT 1 FROM portal.semantic_namespace WHERE code IN ('core', 'engine')
  ), ''::text;

  FOR v_rec IN
    SELECT r.request_code, r.version, r.target_kind, r.target_name, r.row_type::text AS row_type_name
    FROM portal.semantic_request r
  LOOP
    IF v_rec.target_kind = 'function' THEN
      v_fn := to_regprocedure(v_rec.target_name || '(integer,jsonb,integer)');
      RETURN QUERY SELECT
        format('target_exists:%s', v_rec.request_code),
        v_fn IS NOT NULL,
        COALESCE(v_rec.target_name, '');
    ELSIF v_rec.target_kind = 'template' THEN
      v_fn := to_regprocedure(
        v_rec.target_name || '(integer,jsonb,integer,text,text[])'
      );
      RETURN QUERY SELECT
        format('target_exists:%s', v_rec.request_code),
        v_fn IS NOT NULL,
        COALESCE(v_rec.target_name, '');
    END IF;

    RETURN QUERY SELECT
      format('row_type_exists:%s', v_rec.request_code),
      to_regtype(v_rec.row_type_name) IS NOT NULL,
      v_rec.row_type_name;
  END LOOP;

  RETURN QUERY SELECT 'workflow_action_classified'::text,
    NOT EXISTS (
      SELECT 1 FROM wf.workflow_action a
      WHERE a.level IS NULL OR a.namespace IS NULL
    ),
    ''::text;
END;
$$;
