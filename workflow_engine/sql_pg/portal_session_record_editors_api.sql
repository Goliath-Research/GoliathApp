/*
  Session-gated record editors for the platform host Workflows pages.
  Callable by goliath_portal only. Every writer:
    - requires an operator session with an active scope,
    - requires the NavTree entitlement of the page that edits the record,
    - requires the platform.model.author permission (workflow catalogs are platform model),
    - writes one row to portal.record_editor_audit,
    - delegates to the existing engine writers where they exist.

  Actions are Meta class methods ("Meta"."Methods" + "Meta"."MethodParams"). wf.workflow_action
  is the engine catalog the method binds to (ImplKind = 'action', ImplRef = action_name) and is
  synchronised from the method on save; it is never edited as a parallel untyped record.
*/

CREATE TABLE IF NOT EXISTS portal.record_editor_audit (
  audit_id bigserial PRIMARY KEY,
  session_id integer NOT NULL,
  user_id integer NOT NULL,
  scope_id integer NULL,
  entity text NOT NULL,
  action_code text NOT NULL,
  record_key text NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS ix_record_editor_audit_entity
  ON portal.record_editor_audit (entity, created_at_utc DESC);

CREATE OR REPLACE FUNCTION portal.fn_session_record_editor_require(
  p_session_token text,
  p_node_paths text[]
)
RETURNS TABLE (session_id integer, user_id integer, active_scope_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_operator_require(p_session_token, NULL) LIMIT 1;
  PERFORM portal.fn_session_require_any_nav(p_session_token, p_node_paths);
  IF NOT portal.fn_semantic_session_has_permission(v_ctx.user_id, 'platform.model.author') THEN
    PERFORM portal.fn_semantic_raise('GS403', 'platform model author permission denied');
  END IF;
  RETURN QUERY SELECT v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_record_editor_audit(
  p_ctx_session_id integer,
  p_ctx_user_id integer,
  p_ctx_scope_id integer,
  p_entity text,
  p_action text,
  p_record_key text,
  p_payload jsonb
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  INSERT INTO portal.record_editor_audit (session_id, user_id, scope_id, entity, action_code, record_key, payload)
  VALUES (p_ctx_session_id, p_ctx_user_id, p_ctx_scope_id, p_entity, p_action, p_record_key,
          COALESCE(p_payload, '{}'::jsonb));
$$;

CREATE OR REPLACE FUNCTION portal.fn_doc_text(p_doc jsonb, p_key text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT NULLIF(btrim(p_doc->>p_key), '');
$$;

-- ── Actions = Meta class methods ───────────────────────────────────────────

/*
  Effective methods per class: methods declared on the class plus methods inherited from
  ancestors that the class (or a closer ancestor) does not redeclare. `inherited` marks rows
  declared on an ancestor; `is_override` marks redeclarations of an ancestor method.
*/
CREATE OR REPLACE FUNCTION portal.sp_session_list_class_methods(p_session_token text)
RETURNS TABLE (
  class_name text,
  method_id integer,
  method_name text,
  declared_on_class text,
  inherited boolean,
  inheritance_depth integer,
  is_override boolean,
  is_abstract boolean,
  is_final boolean,
  impl_kind text,
  impl_ref text,
  description text,
  param_count integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(
    p_session_token, ARRAY['/app/workflows/actions', '/app/meta/methods']
  );
  RETURN QUERY
  WITH candidates AS (
    SELECT
      cc."DescendantID" AS class_id,
      m."ID" AS method_id,
      m."Name" AS method_name,
      m."ClassID" AS declared_on_id,
      cc."Depth" AS depth,
      row_number() OVER (
        PARTITION BY cc."DescendantID", m."Name" ORDER BY cc."Depth"
      ) AS rn
    FROM "Meta"."ClassClosure" cc
    JOIN "Meta"."Methods" m ON m."ClassID" = cc."AncestorID"
  )
  SELECT
    c."Name"::text,
    m."ID",
    m."Name"::text,
    dc."Name"::text,
    (cand.depth > 0),
    cand.depth,
    m."IsOverride",
    m."IsAbstract",
    m."IsFinal",
    m."ImplKind",
    m."ImplRef",
    m."Description",
    (SELECT count(*)::int FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = m."ID")
  FROM candidates cand
  JOIN "Meta"."Classes" c ON c."ID" = cand.class_id
  JOIN "Meta"."Methods" m ON m."ID" = cand.method_id
  JOIN "Meta"."Classes" dc ON dc."ID" = cand.declared_on_id
  WHERE cand.rn = 1
  ORDER BY c."Name", (cand.depth > 0), m."Name";
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_method_param_default_schema(p_type_id bigint)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, pg_temp
AS $$
  SELECT CASE
    WHEN t.class_id IS NOT NULL THEN
      jsonb_build_object('$ref', 'goliath:meta/class/' || c."Name")
    ELSE "Meta".fn_effective_type_fragment(t.id) - '$schema' - '$id'
  END
  FROM wf.data_type t
  LEFT JOIN "Meta"."Classes" c ON c."ID" = t.class_id
  WHERE t.id = p_type_id;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_get_class_method(
  p_session_token text,
  p_method_id integer
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, pg_temp
AS $$
DECLARE
  v_doc jsonb;
BEGIN
  PERFORM portal.fn_session_require_any_nav(
    p_session_token, ARRAY['/app/workflows/actions', '/app/meta/methods']
  );
  SELECT jsonb_strip_nulls(jsonb_build_object(
    'method_id', m."ID",
    'class_name', c."Name",
    'method_name', m."Name",
    'description', m."Description",
    'impl_kind', COALESCE(m."ImplKind", 'abstract'),
    'impl_ref', CASE WHEN m."ImplKind" = 'action' THEN NULL ELSE m."ImplRef" END,
    'action_name', CASE WHEN m."ImplKind" = 'action' THEN m."ImplRef" END,
    'return_type_id', m."ReturnTypeID",
    'is_override', m."IsOverride",
    'is_final', m."IsFinal",
    'parameters', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'name', mp."Name", 'type_id', mp."TypeID", 'required', mp."Required"
      ) ORDER BY mp."Ordinal")
      FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = m."ID"
    ), '[]'::jsonb),
    'action', CASE WHEN m."ImplKind" = 'action' THEN (
      SELECT jsonb_strip_nulls(jsonb_build_object(
        'capability', a.capability,
        'implementation_status', a.implementation_status,
        'execution_mode', a.execution_mode,
        'cli_tool', a.cli_tool,
        'in_process_handler', a.in_process_handler,
        'max_per_worker', a.max_per_worker,
        'exclusive_worker', a.exclusive_worker,
        'can_pause', a.can_pause,
        'can_continue', a.can_continue
      ))
      FROM wf.workflow_action a WHERE a.action_name = m."ImplRef"
    ) END,
    'defaults_schema', jsonb_build_object(
      'type', 'object',
      'properties', COALESCE((
        SELECT jsonb_object_agg(mp."Name", portal.fn_method_param_default_schema(mp."TypeID"))
        FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = m."ID"
      ), '{}'::jsonb)
    ),
    'defaults', COALESCE((
      SELECT jsonb_object_agg(mp."Name", mp."DefaultValue")
      FROM "Meta"."MethodParams" mp
      WHERE mp."MethodID" = m."ID" AND mp."DefaultValue" IS NOT NULL
    ), '{}'::jsonb)
  ))
  INTO v_doc
  FROM "Meta"."Methods" m
  JOIN "Meta"."Classes" c ON c."ID" = m."ClassID"
  WHERE m."ID" = p_method_id;

  IF v_doc IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'method not found');
  END IF;
  RETURN v_doc;
END;
$$;

/*
  Create or update a class method and its typed parameters, then synchronise the bound
  wf.workflow_action catalog row:
    - ImplKind 'action' requires ImplRef; a missing catalog row is created.
    - Redeclaring an ancestor method marks IsOverride; overriding a final method is rejected.
    - When the method declares parameters, the published params type
      (meta/class/<Class>/<Method>.Params) becomes the action input type and input schema.
      Methods without parameters leave existing catalog input schemas untouched.
*/
CREATE OR REPLACE FUNCTION portal.sp_session_save_class_method(
  p_session_token text,
  p_method_id integer,
  p_document jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_doc jsonb := COALESCE(p_document, '{}'::jsonb);
  v_class_id integer;
  v_method_id integer := p_method_id;
  v_name text;
  v_impl_kind text := lower(COALESCE(portal.fn_doc_text(v_doc, 'impl_kind'), 'action'));
  v_impl_ref text := COALESCE(
    CASE WHEN lower(COALESCE(portal.fn_doc_text(p_document, 'impl_kind'), 'action')) = 'action'
         THEN portal.fn_doc_text(p_document, 'action_name') END,
    portal.fn_doc_text(p_document, 'impl_ref')
  );
  v_return_type bigint := NULLIF(v_doc->>'return_type_id', '')::bigint;
  v_is_final boolean := COALESCE((v_doc->>'is_final')::boolean, false);
  v_override boolean;
  v_param jsonb;
  v_ordinal int := 0;
  v_params_type bigint;
  v_action jsonb := COALESCE(v_doc->'action', '{}'::jsonb);
  v_old_defaults jsonb;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(
    p_session_token, ARRAY['/app/workflows/actions', '/app/meta/methods']
  ) LIMIT 1;

  IF v_impl_kind = 'abstract' THEN
    v_impl_kind := NULL;
    v_impl_ref := NULL;
  ELSIF v_impl_kind NOT IN ('action', 'sql', 'python') THEN
    PERFORM portal.fn_semantic_raise('GS400', 'impl_kind must be action, sql, python or abstract');
  ELSIF v_impl_ref IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'impl_ref is required for an implemented method');
  END IF;

  IF v_method_id IS NOT NULL THEN
    SELECT m."ClassID", m."Name" INTO v_class_id, v_name
    FROM "Meta"."Methods" m WHERE m."ID" = v_method_id;
    IF v_class_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'method not found');
    END IF;
  ELSE
    v_name := portal.fn_doc_text(v_doc, 'method_name');
    IF v_name IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS400', 'method_name is required');
    END IF;
    SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c
    WHERE c."Name" = portal.fn_doc_text(v_doc, 'class_name');
    IF v_class_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS400', 'class_name must name an existing Meta class');
    END IF;
    IF EXISTS (SELECT 1 FROM "Meta"."Methods" m WHERE m."ClassID" = v_class_id AND m."Name" = v_name) THEN
      PERFORM portal.fn_semantic_raise('GS409', 'method already exists on this class');
    END IF;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM "Meta"."ClassClosure" cc
    JOIN "Meta"."Methods" am ON am."ClassID" = cc."AncestorID"
    WHERE cc."DescendantID" = v_class_id AND cc."Depth" > 0
      AND am."Name" = v_name AND am."IsFinal"
  ) THEN
    PERFORM portal.fn_semantic_raise('GS400', 'cannot override a final ancestor method');
  END IF;
  v_override := EXISTS (
    SELECT 1
    FROM "Meta"."ClassClosure" cc
    JOIN "Meta"."Methods" am ON am."ClassID" = cc."AncestorID"
    WHERE cc."DescendantID" = v_class_id AND cc."Depth" > 0 AND am."Name" = v_name
  );

  IF v_return_type IS NOT NULL AND NOT EXISTS (SELECT 1 FROM wf.data_type t WHERE t.id = v_return_type) THEN
    PERFORM portal.fn_semantic_raise('GS400', 'return_type_id must reference a data type');
  END IF;

  IF v_impl_kind = 'action' THEN
    IF NOT EXISTS (SELECT 1 FROM wf.workflow_action a WHERE a.action_name = v_impl_ref) THEN
      CALL wf.wf_repo_upsert_workflow_action(v_impl_ref, portal.fn_doc_text(v_action, 'capability'));
    END IF;
  END IF;

  IF v_method_id IS NULL THEN
    INSERT INTO "Meta"."Methods" (
      "ClassID", "Name", "Description", "ReturnTypeID", "IsAbstract", "IsOverride", "IsFinal",
      "ImplKind", "ImplRef"
    ) VALUES (
      v_class_id, v_name, portal.fn_doc_text(v_doc, 'description'), v_return_type,
      v_impl_kind IS NULL, v_override, v_is_final, v_impl_kind, v_impl_ref
    )
    RETURNING "ID" INTO v_method_id;
  ELSE
    UPDATE "Meta"."Methods" m SET
      "Description" = portal.fn_doc_text(v_doc, 'description'),
      "ReturnTypeID" = v_return_type,
      "IsAbstract" = (v_impl_kind IS NULL),
      "IsOverride" = v_override,
      "IsFinal" = v_is_final,
      "ImplKind" = v_impl_kind,
      "ImplRef" = v_impl_ref
    WHERE m."ID" = v_method_id;
  END IF;

  IF v_doc ? 'parameters' THEN
    IF jsonb_typeof(v_doc->'parameters') <> 'array' THEN
      PERFORM portal.fn_semantic_raise('GS400', 'parameters must be a list');
    END IF;
    SELECT jsonb_object_agg(mp."Name", jsonb_build_object('type', mp."TypeID", 'value', mp."DefaultValue"))
    INTO v_old_defaults
    FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = v_method_id AND mp."DefaultValue" IS NOT NULL;

    DELETE FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = v_method_id;
    FOR v_param IN SELECT value FROM jsonb_array_elements(v_doc->'parameters')
    LOOP
      v_ordinal := v_ordinal + 1;
      IF portal.fn_doc_text(v_param, 'name') IS NULL THEN
        PERFORM portal.fn_semantic_raise('GS400', format('parameter %s needs a name', v_ordinal));
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM wf.data_type t WHERE t.id = NULLIF(v_param->>'type_id', '')::bigint
      ) THEN
        PERFORM portal.fn_semantic_raise(
          'GS400', format('parameter %s needs a data type', portal.fn_doc_text(v_param, 'name'))
        );
      END IF;
      INSERT INTO "Meta"."MethodParams" ("MethodID", "Ordinal", "Name", "TypeID", "Required", "DefaultValue")
      VALUES (
        v_method_id,
        v_ordinal,
        portal.fn_doc_text(v_param, 'name'),
        (v_param->>'type_id')::bigint,
        COALESCE((v_param->>'required')::boolean, true),
        CASE
          WHEN (v_old_defaults -> portal.fn_doc_text(v_param, 'name') ->> 'type')::bigint
               = (v_param->>'type_id')::bigint
          THEN v_old_defaults -> portal.fn_doc_text(v_param, 'name') -> 'value'
        END
      );
    END LOOP;
  END IF;

  IF v_impl_kind = 'action' THEN
    UPDATE wf.workflow_action a SET
      capability = COALESCE(portal.fn_doc_text(v_action, 'capability'), a.capability),
      implementation_status = COALESCE(portal.fn_doc_text(v_action, 'implementation_status'), a.implementation_status),
      execution_mode = COALESCE(portal.fn_doc_text(v_action, 'execution_mode'), a.execution_mode),
      cli_tool = COALESCE(portal.fn_doc_text(v_action, 'cli_tool'), a.cli_tool),
      in_process_handler = COALESCE(portal.fn_doc_text(v_action, 'in_process_handler'), a.in_process_handler),
      max_per_worker = CASE WHEN v_action ? 'max_per_worker'
                            THEN NULLIF(v_action->>'max_per_worker', '')::int ELSE a.max_per_worker END,
      exclusive_worker = COALESCE((v_action->>'exclusive_worker')::boolean, a.exclusive_worker),
      can_pause = COALESCE((v_action->>'can_pause')::boolean, a.can_pause),
      can_continue = COALESCE((v_action->>'can_continue')::boolean, a.can_continue),
      output_type_id = COALESCE(v_return_type, a.output_type_id)
    WHERE a.action_name = v_impl_ref;

    IF EXISTS (SELECT 1 FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = v_method_id) THEN
      v_params_type := "Meta".sp_meta_publish_method_params_type(v_method_id, false);
      UPDATE wf.workflow_action a SET input_type_id = v_params_type WHERE a.action_name = v_impl_ref;
      CALL wf.wf_repo_upsert_action_schema(
        v_impl_ref, 'input', "Meta".fn_method_params_json_schema(v_method_id)
      );
    END IF;
  END IF;

  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
    'class_method', CASE WHEN p_method_id IS NULL THEN 'create' ELSE 'update' END,
    v_method_id::text, v_doc - 'defaults' - 'defaults_schema'
  );
  RETURN v_method_id;
END;
$$;

/* Parameter defaults, edited through a grid built from each parameter's data type schema. */
CREATE OR REPLACE FUNCTION portal.sp_session_save_method_param_defaults(
  p_session_token text,
  p_method_id integer,
  p_defaults jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_key text;
  v_updated int := 0;
  v_impl_kind text;
  v_impl_ref text;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(
    p_session_token, ARRAY['/app/workflows/actions', '/app/meta/methods']
  ) LIMIT 1;
  IF p_defaults IS NULL OR jsonb_typeof(p_defaults) <> 'object' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'defaults must be an object');
  END IF;
  SELECT m."ImplKind", m."ImplRef" INTO v_impl_kind, v_impl_ref
  FROM "Meta"."Methods" m WHERE m."ID" = p_method_id;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'method not found');
  END IF;
  FOR v_key IN SELECT jsonb_object_keys(p_defaults)
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = p_method_id AND mp."Name" = v_key
    ) THEN
      PERFORM portal.fn_semantic_raise('GS400', format('unknown parameter %s', v_key));
    END IF;
  END LOOP;
  UPDATE "Meta"."MethodParams" mp
  SET "DefaultValue" = CASE
    WHEN p_defaults ? mp."Name" AND p_defaults->mp."Name" <> 'null'::jsonb THEN p_defaults->mp."Name"
    ELSE NULL
  END
  WHERE mp."MethodID" = p_method_id;
  GET DIAGNOSTICS v_updated = ROW_COUNT;

  IF v_impl_kind = 'action' AND v_updated > 0 THEN
    UPDATE wf.workflow_action a
    SET input_type_id = "Meta".sp_meta_publish_method_params_type(p_method_id, false)
    WHERE a.action_name = v_impl_ref;
    CALL wf.wf_repo_upsert_action_schema(v_impl_ref, 'input', "Meta".fn_method_params_json_schema(p_method_id));
  END IF;

  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
    'class_method', 'defaults', p_method_id::text, p_defaults
  );
  RETURN v_updated;
END;
$$;

-- ── Domain programs (cfg.domain_program) ───────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_get_domain_program(
  p_session_token text,
  p_name text,
  p_version text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
DECLARE
  v_doc jsonb;
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/domain-programs');
  SELECT jsonb_strip_nulls(jsonb_build_object(
    'name', dp.name,
    'version', dp.version,
    'status', dp.status,
    'description', dp.document_json->>'description',
    'program_version', dp.document_json->>'programVersion',
    'project_path', dp.document_json->>'projectPath',
    'step_count', CASE WHEN jsonb_typeof(dp.document_json->'body') = 'array'
                       THEN jsonb_array_length(dp.document_json->'body') ELSE 0 END,
    'compiled_workflow_version_id', dp.compiled_workflow_version_id
  ))
  INTO v_doc
  FROM cfg.domain_program dp
  WHERE dp.name = p_name AND dp.version = p_version;
  IF v_doc IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'domain program not found');
  END IF;
  RETURN v_doc;
END;
$$;

/*
  Save program metadata as a draft. The program body (steps) is preserved: an existing
  version keeps its body; a new version copies the body of the latest version of the same
  program. Published or retired versions are immutable; save under a new version instead.
*/
CREATE OR REPLACE FUNCTION portal.sp_session_save_domain_program(
  p_session_token text,
  p_document jsonb
)
RETURNS TABLE (name text, version text, status text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_ctx record;
  v_doc jsonb := COALESCE(p_document, '{}'::jsonb);
  v_name text := portal.fn_doc_text(v_doc, 'name');
  v_version text := portal.fn_doc_text(v_doc, 'version');
  v_existing record;
  v_base jsonb;
  v_new jsonb;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/domain-programs']) LIMIT 1;
  IF v_name IS NULL OR v_version IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'name and version are required');
  END IF;

  SELECT dp.status, dp.document_json INTO v_existing
  FROM cfg.domain_program dp WHERE dp.name = v_name AND dp.version = v_version;
  IF FOUND THEN
    IF v_existing.status <> 'draft' THEN
      PERFORM portal.fn_semantic_raise('GS409', 'published versions are immutable; save under a new version');
    END IF;
    v_base := v_existing.document_json;
  ELSE
    SELECT dp.document_json INTO v_base
    FROM cfg.domain_program dp WHERE dp.name = v_name
    ORDER BY dp.created_at_utc DESC, dp.id DESC LIMIT 1;
    v_base := COALESCE(v_base, jsonb_build_object('name', v_name, 'body', '[]'::jsonb));
  END IF;

  v_new := v_base || jsonb_strip_nulls(jsonb_build_object(
    'name', v_name,
    'description', portal.fn_doc_text(v_doc, 'description'),
    'programVersion', portal.fn_doc_text(v_doc, 'program_version'),
    'projectPath', portal.fn_doc_text(v_doc, 'project_path')
  ));

  PERFORM 1 FROM portal.sp_upsert_domain_program(v_name, v_version, 'draft', v_new);
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
    'domain_program', 'save', v_name || '@' || v_version, v_doc
  );
  RETURN QUERY SELECT v_name, v_version, 'draft'::text;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_publish_domain_program(
  p_session_token text,
  p_name text,
  p_version text
)
RETURNS TABLE (name text, version text, status text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, cfg, wf, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_ctx record;
  r record;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/domain-programs']) LIMIT 1;
  SELECT * INTO r FROM portal.sp_publish_domain_program(p_name, p_version, NULL) LIMIT 1;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
    'domain_program', 'publish', p_name || '@' || p_version, '{}'::jsonb
  );
  RETURN QUERY SELECT r.name, r.version, r.status;
END;
$$;

-- ── Clusters and worker enrollments ─────────────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_list_clusters(p_session_token text)
RETURNS TABLE (
  cluster_id bigint,
  cluster_key text,
  name text,
  provider text,
  status text,
  shared_storage_uri text,
  worker_mount_path text,
  worker_count integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(
    p_session_token, ARRAY['/app/workflows/workers', '/app/operations/worker-fleet']
  );
  RETURN QUERY
  SELECT c.id, c.cluster_key, c.name, c.provider, c.status::text, c.shared_storage_uri,
         c.worker_mount_path,
         (SELECT count(*)::int FROM wf.worker w WHERE w.cluster_id = c.id)
  FROM wf.cluster c
  ORDER BY c.name;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_get_cluster(p_session_token text, p_cluster_key text)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
DECLARE
  v_doc jsonb;
BEGIN
  PERFORM portal.fn_session_require_any_nav(
    p_session_token, ARRAY['/app/workflows/workers', '/app/operations/worker-fleet']
  );
  SELECT jsonb_strip_nulls(jsonb_build_object(
    'cluster_key', c.cluster_key,
    'name', c.name,
    'status', c.status,
    'shared_storage_uri', c.shared_storage_uri,
    'worker_mount_path', c.worker_mount_path,
    'allowed_source_cidrs', CASE WHEN jsonb_typeof(c.allowed_source_cidrs) = 'array'
                                 THEN c.allowed_source_cidrs END
  ))
  INTO v_doc
  FROM wf.cluster c WHERE c.cluster_key = p_cluster_key;
  IF v_doc IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'cluster not found');
  END IF;
  RETURN v_doc;
END;
$$;

/* Cluster metadata only: never starts, stops or provisions workers or pods. */
CREATE OR REPLACE FUNCTION portal.sp_session_save_cluster(p_session_token text, p_document jsonb)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_doc jsonb := COALESCE(p_document, '{}'::jsonb);
  v_key text := portal.fn_doc_text(v_doc, 'cluster_key');
  v_status text := upper(COALESCE(portal.fn_doc_text(v_doc, 'status'), 'ACTIVE'));
  v_cidrs jsonb := v_doc->'allowed_source_cidrs';
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/workers']) LIMIT 1;
  IF v_key IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'cluster_key is required');
  END IF;
  IF v_status NOT IN ('ACTIVE', 'DISABLED') THEN
    PERFORM portal.fn_semantic_raise('GS400', 'status must be ACTIVE or DISABLED');
  END IF;
  IF v_cidrs IS NOT NULL AND v_cidrs <> 'null'::jsonb AND jsonb_typeof(v_cidrs) <> 'array' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'allowed_source_cidrs must be a list');
  END IF;
  IF v_cidrs = '[]'::jsonb OR v_cidrs = 'null'::jsonb THEN
    v_cidrs := NULL;
  END IF;
  PERFORM 1 FROM portal.sp_upsert_cluster(
    v_key,
    portal.fn_doc_text(v_doc, 'name'),
    COALESCE(portal.fn_doc_text(v_doc, 'shared_storage_uri'),
             (SELECT c.shared_storage_uri FROM wf.cluster c WHERE c.cluster_key = v_key), '/work/goliath'),
    COALESCE(portal.fn_doc_text(v_doc, 'worker_mount_path'),
             (SELECT c.worker_mount_path FROM wf.cluster c WHERE c.cluster_key = v_key), '/work/goliath'),
    v_cidrs,
    v_status
  );
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'cluster', 'save', v_key, v_doc
  );
  RETURN v_key;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_save_worker_enrollment(p_session_token text, p_document jsonb)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_doc jsonb := COALESCE(p_document, '{}'::jsonb);
  v_id bigint;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/workers']) LIMIT 1;
  IF portal.fn_doc_text(v_doc, 'cluster_key') IS NULL
     OR portal.fn_doc_text(v_doc, 'public_ip') IS NULL
     OR portal.fn_doc_text(v_doc, 'external_worker_key') IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'cluster_key, public_ip and external_worker_key are required');
  END IF;
  SELECT e.id INTO v_id FROM portal.sp_upsert_worker_enrollment(
    portal.fn_doc_text(v_doc, 'cluster_key'),
    portal.fn_doc_text(v_doc, 'public_ip'),
    portal.fn_doc_text(v_doc, 'external_worker_key')
  ) e;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'worker_enrollment', 'save',
    portal.fn_doc_text(v_doc, 'cluster_key') || '/' || portal.fn_doc_text(v_doc, 'external_worker_key'), v_doc
  );
  RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_revoke_worker_enrollment(
  p_session_token text,
  p_cluster_key text,
  p_external_worker_key text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_status text;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/workers']) LIMIT 1;
  SELECT r.status INTO v_status
  FROM portal.sp_revoke_worker_enrollment(p_cluster_key, p_external_worker_key) r;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'worker_enrollment', 'revoke',
    p_cluster_key || '/' || p_external_worker_key, '{}'::jsonb
  );
  RETURN v_status;
END;
$$;

-- ── Event subscriptions (wf.event_subscription) ───────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_get_event_subscription(
  p_session_token text,
  p_subscription_id bigint
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
DECLARE
  v_doc jsonb;
BEGIN
  PERFORM portal.fn_session_operator_require(p_session_token, '/app/workflows/subscriptions');
  SELECT jsonb_build_object(
    'subscription_id', s.id,
    'event_type', et.name,
    'workflow_version_id', s.workflow_version_id,
    'mode', s.mode,
    'enabled', s.enabled,
    'filter', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'key', f.key,
        'value', CASE WHEN jsonb_typeof(f.value) = 'string' THEN f.value #>> '{}' ELSE f.value::text END,
        'value_type', CASE jsonb_typeof(f.value)
                        WHEN 'number' THEN 'number'
                        WHEN 'boolean' THEN 'boolean'
                        ELSE 'string' END
      ) ORDER BY f.key)
      FROM jsonb_each(CASE WHEN jsonb_typeof(s.filter_json) = 'object' THEN s.filter_json ELSE '{}'::jsonb END) f
    ), '[]'::jsonb)
  )
  INTO v_doc
  FROM wf.event_subscription s
  JOIN wf.event_type et ON et.id = s.event_type_id
  WHERE s.id = p_subscription_id;
  IF v_doc IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'event subscription not found');
  END IF;
  RETURN v_doc;
END;
$$;

/*
  Create (p_subscription_id NULL) or edit an event subscription. The payload filter is a list
  of {key, value, value_type} equality conditions, stored as the engine's top-level
  filter_json object (wf.wf_event_filter_matches).
*/
CREATE OR REPLACE FUNCTION portal.sp_session_save_event_subscription(
  p_session_token text,
  p_subscription_id bigint,
  p_document jsonb
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_doc jsonb := COALESCE(p_document, '{}'::jsonb);
  v_event_type_id bigint;
  v_version_id bigint := NULLIF(v_doc->>'workflow_version_id', '')::bigint;
  v_mode text := COALESCE(portal.fn_doc_text(v_doc, 'mode'), 'start_instance');
  v_filter jsonb := '{}'::jsonb;
  v_cond jsonb;
  v_val jsonb;
  v_id bigint := p_subscription_id;
BEGIN
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY['/app/workflows/subscriptions']) LIMIT 1;

  SELECT et.id INTO v_event_type_id FROM wf.event_type et
  WHERE et.name = portal.fn_doc_text(v_doc, 'event_type');
  IF v_event_type_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'event_type must name an existing event type');
  END IF;
  IF v_version_id IS NULL OR NOT EXISTS (SELECT 1 FROM wf.workflow_version v WHERE v.id = v_version_id) THEN
    PERFORM portal.fn_semantic_raise('GS400', 'workflow_version_id must reference a workflow version');
  END IF;
  IF v_mode NOT IN ('start_instance', 'signal_wait', 'start_or_signal') THEN
    PERFORM portal.fn_semantic_raise('GS400', 'mode must be start_instance, signal_wait or start_or_signal');
  END IF;

  IF v_doc ? 'filter' AND jsonb_typeof(v_doc->'filter') = 'array' THEN
    FOR v_cond IN SELECT value FROM jsonb_array_elements(v_doc->'filter')
    LOOP
      IF portal.fn_doc_text(v_cond, 'key') IS NULL THEN
        PERFORM portal.fn_semantic_raise('GS400', 'every filter condition needs a key');
      END IF;
      v_val := CASE lower(COALESCE(v_cond->>'value_type', 'string'))
        WHEN 'number' THEN to_jsonb((v_cond->>'value')::numeric)
        WHEN 'boolean' THEN to_jsonb((v_cond->>'value')::boolean)
        ELSE to_jsonb(COALESCE(v_cond->>'value', ''))
      END;
      v_filter := v_filter || jsonb_build_object(btrim(v_cond->>'key'), v_val);
    END LOOP;
  END IF;

  IF v_id IS NULL THEN
    INSERT INTO wf.event_subscription (event_type_id, workflow_version_id, mode, filter_json, enabled)
    VALUES (v_event_type_id, v_version_id, v_mode, NULLIF(v_filter, '{}'::jsonb),
            COALESCE((v_doc->>'enabled')::boolean, true))
    RETURNING id INTO v_id;
  ELSE
    UPDATE wf.event_subscription s SET
      event_type_id = v_event_type_id,
      workflow_version_id = v_version_id,
      mode = v_mode,
      filter_json = CASE WHEN v_doc ? 'filter' THEN NULLIF(v_filter, '{}'::jsonb) ELSE s.filter_json END,
      enabled = COALESCE((v_doc->>'enabled')::boolean, s.enabled)
    WHERE s.id = v_id;
    IF NOT FOUND THEN
      PERFORM portal.fn_semantic_raise('GS404', 'event subscription not found');
    END IF;
  END IF;

  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'event_subscription',
    CASE WHEN p_subscription_id IS NULL THEN 'create' ELSE 'update' END, v_id::text, v_doc
  );
  RETURN v_id;
END;
$$;
