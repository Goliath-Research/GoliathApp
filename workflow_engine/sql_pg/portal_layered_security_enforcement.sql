/*
  Hook layered security into Meta instance and semantic read paths.
*/

CREATE OR REPLACE FUNCTION portal.sp_session_meta_obj_insert(
  p_session_token text,
  p_class_name text,
  p_document jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
  v_obj_id int;
  v_doc jsonb;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_resolve(p_session_token) LIMIT 1;
  IF v_ctx.session_id IS NULL OR COALESCE(v_ctx.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;
  IF v_ctx.active_scope_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'active scope required for meta instance access');
  END IF;

  IF NOT portal.fn_session_meta_permission_in_active_scope(
    v_ctx.user_id, 'meta.schema.read', v_ctx.active_scope_id
  ) THEN
    v_class_id := portal.sp_session_meta_resolve_class(p_session_token, p_class_name);
    IF NOT portal.fn_meta_effective_class_action_explicit(
      v_ctx.user_id, v_ctx.active_scope_id, v_class_id, 'create'
    ) THEN
      PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied');
    END IF;
  ELSE
    v_class_id := portal.sp_session_meta_resolve_class(p_session_token, p_class_name);
  END IF;
  PERFORM portal.fn_meta_assert_class_action(v_ctx.user_id, v_ctx.active_scope_id, v_class_id, 'create');

  v_doc := portal.fn_session_meta_strip_tenancy_keys(p_document);
  v_obj_id := "Meta".sp_obj_insert(v_class_id, COALESCE(v_doc, '{}'::jsonb));

  INSERT INTO portal."ScopedMetaObjects" ("ObjID", "ScopeID")
  VALUES (v_obj_id, v_ctx.active_scope_id);

  RETURN v_obj_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_obj_update(
  p_session_token text,
  p_obj_id integer,
  p_document jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_doc jsonb;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_resolve(p_session_token) LIMIT 1;
  IF v_ctx.session_id IS NULL OR COALESCE(v_ctx.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;
  IF v_ctx.active_scope_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'active scope required for meta instance access');
  END IF;

  PERFORM portal.fn_session_meta_require_mutation_gate(
    v_ctx.user_id, v_ctx.active_scope_id, NULL, p_obj_id, 'update'
  );
  PERFORM portal.fn_session_meta_assert_obj_in_active_scope(p_obj_id, v_ctx.active_scope_id);
  PERFORM portal.fn_meta_assert_object_action(v_ctx.user_id, v_ctx.active_scope_id, p_obj_id, 'update');

  v_doc := portal.fn_session_meta_strip_tenancy_keys(p_document);
  PERFORM "Meta".sp_obj_update(p_obj_id, COALESCE(v_doc, '{}'::jsonb));
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_obj_get(
  p_session_token text,
  p_obj_id integer
)
RETURNS TABLE (
  obj_id integer,
  class_id integer,
  class_name text,
  document jsonb
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_resolve(p_session_token) LIMIT 1;
  IF v_ctx.session_id IS NULL OR COALESCE(v_ctx.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;
  IF v_ctx.active_scope_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'active scope required for meta instance access');
  END IF;

  PERFORM portal.fn_session_meta_assert_obj_in_active_scope(p_obj_id, v_ctx.active_scope_id);
  PERFORM portal.fn_meta_assert_object_action(v_ctx.user_id, v_ctx.active_scope_id, p_obj_id, 'read');

  RETURN QUERY
  SELECT
    o."ID"::integer,
    o."ClassID"::integer,
    c."Name"::text,
    "Meta".fn_merged_obj_document(o."ID")
  FROM "Meta"."Objs" o
  JOIN "Meta"."Classes" c ON c."ID" = o."ClassID"
  WHERE o."ID" = p_obj_id;
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
SET search_path = portal, "RBAC", cfg, public, pg_temp
AS $$
DECLARE
  v_sess record;
  v_req portal.semantic_request%ROWTYPE;
  v_limit integer;
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

  IF v_sess.active_scope_id IS NOT NULL AND v_entity.meta_class_id IS NOT NULL THEN
    PERFORM portal.fn_meta_assert_class_action(
      v_sess.user_id,
      v_sess.active_scope_id,
      v_entity.meta_class_id,
      'read'
    );
  END IF;

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

    IF v_req.target_name = 'portal.fn_semantic_core_filter_organizations' THEN
      RETURN QUERY
      SELECT to_jsonb(r)
      FROM portal.fn_semantic_core_filter_organizations(
        v_sess.user_id,
        COALESCE(p_params, '{}'::jsonb),
        v_limit,
        v_req.entity_id,
        COALESCE(p_filter, v_req.filter_template, '{}'::jsonb)
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
