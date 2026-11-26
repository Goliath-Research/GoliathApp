/*
  Session-gated record editors for the semantic layer (namespaces, entities, attributes,
  requests). Callable by goliath_portal only. Every writer:
    - requires the semantic page entitlement and platform.model.author (record-editor gate),
    - requires God Architect for the platform namespaces (platform, portal, core),
    - writes one row to portal.record_editor_audit.

  Request parameters and filters are edited as typed lists and compiled here into the stored
  params_schema / filter_template; result_schema is derived from the row type. Stored schemas
  that use features the list editor cannot represent are kept verbatim and their parameter
  list is read-only. Function targets must be existing functions with the runner signature
  (integer, jsonb, integer); template targets must be ones the runner implements.

  Applied after platform_god_architect.sql and meta_model_semantic.sql.
*/

CREATE OR REPLACE FUNCTION portal.fn_semantic_namespace_is_platform(p_namespace text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT lower(btrim(coalesce(p_namespace, ''))) IN ('platform', 'portal', 'core');
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_editor_require(
  p_session_token text,
  p_node_path text,
  p_namespace text
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
  SELECT * INTO v_ctx
  FROM portal.fn_session_record_editor_require(p_session_token, ARRAY[p_node_path])
  LIMIT 1;
  IF portal.fn_semantic_namespace_is_platform(p_namespace) THEN
    PERFORM 1 FROM portal.fn_session_model_author_require_god(p_session_token, NULL);
  END IF;
  RETURN QUERY SELECT v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_ident(p_value text, p_label text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  v text := lower(btrim(coalesce(p_value, '')));
BEGIN
  IF v !~ '^[a-z][a-z0-9_]{0,62}$' THEN
    PERFORM portal.fn_semantic_raise(
      'GS400', format('%s must be lower case letters, digits and underscores', p_label)
    );
  END IF;
  RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_sorted_text_array(p_arr jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT COALESCE(jsonb_agg(x ORDER BY x), '[]'::jsonb)
  FROM jsonb_array_elements_text(CASE WHEN jsonb_typeof(p_arr) = 'array' THEN p_arr ELSE '[]'::jsonb END) x;
$$;

/* Canonical form of an edited parameter list (defaults filled, sorted) for comparisons. */
CREATE OR REPLACE FUNCTION portal.fn_semantic_param_list_norm(p_list jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT COALESCE(jsonb_agg(
    jsonb_strip_nulls(jsonb_build_object(
      'name', NULLIF(btrim(x->>'name'), ''),
      'title', NULLIF(btrim(x->>'title'), ''),
      'json_type', x->>'json_type',
      'required', COALESCE((x->>'required')::boolean, false),
      'nullable', COALESCE((x->>'nullable')::boolean, false),
      'minimum', x->'minimum',
      'maximum', x->'maximum',
      'exclusive_minimum', x->'exclusive_minimum'
    )) ORDER BY x->>'name'
  ), '[]'::jsonb)
  FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_list) = 'array' THEN p_list ELSE '[]'::jsonb END) x;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_filter_list_norm(p_list jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT COALESCE(jsonb_agg(
    jsonb_strip_nulls(jsonb_build_object(
      'attribute', NULLIF(btrim(x->>'attribute'), ''),
      'op', NULLIF(btrim(x->>'op'), ''),
      'param', NULLIF(btrim(x->>'param'), '')
    )) ORDER BY ord
  ), '[]'::jsonb)
  FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p_list) = 'array' THEN p_list ELSE '[]'::jsonb END)
       WITH ORDINALITY AS t(x, ord);
$$;

-- ── Params and filters: typed lists <-> stored JSON Schema / filter template ──

CREATE OR REPLACE FUNCTION portal.fn_semantic_params_to_list(p_schema jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  WITH props AS (
    SELECT k AS name, v AS prop, ord
    FROM jsonb_each(COALESCE(p_schema->'properties', '{}'::jsonb)) WITH ORDINALITY AS t(k, v, ord)
  ),
  shaped AS (
    SELECT
      p.name,
      p.ord,
      p.prop,
      (jsonb_typeof(p.prop->'anyOf') = 'array'
        AND jsonb_array_length(p.prop->'anyOf') = 2
        AND (p.prop->'anyOf') @> '[{"type": "null"}]'::jsonb) AS nullable,
      CASE
        WHEN jsonb_typeof(p.prop->'anyOf') = 'array'
          AND jsonb_array_length(p.prop->'anyOf') = 2
          AND (p.prop->'anyOf') @> '[{"type": "null"}]'::jsonb
        THEN (SELECT x FROM jsonb_array_elements(p.prop->'anyOf') x WHERE x <> '{"type": "null"}'::jsonb LIMIT 1)
        ELSE p.prop
      END AS base
    FROM props p
  )
  SELECT COALESCE(jsonb_agg(
    jsonb_strip_nulls(jsonb_build_object(
      'name', s.name,
      'title', s.prop->>'title',
      'json_type', s.base->>'type',
      'required', COALESCE(p_schema->'required', '[]'::jsonb) ? s.name,
      'nullable', s.nullable,
      'minimum', s.base->'minimum',
      'maximum', s.base->'maximum',
      'exclusive_minimum', s.base->'exclusiveMinimum'
    )) ORDER BY s.name
  ), '[]'::jsonb)
  FROM shaped s;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_params_from_list(p_params jsonb, p_title text DEFAULT NULL)
RETURNS jsonb
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  v_item jsonb;
  v_name text;
  v_type text;
  v_base jsonb;
  v_prop jsonb;
  v_title text;
  v_props jsonb := '{}'::jsonb;
  v_required jsonb := '[]'::jsonb;
  v_out jsonb;
BEGIN
  IF p_params IS NULL OR jsonb_typeof(p_params) <> 'array' OR jsonb_array_length(p_params) = 0 THEN
    RETURN '{}'::jsonb;
  END IF;
  FOR v_item IN SELECT * FROM jsonb_array_elements(p_params)
  LOOP
    v_name := portal.fn_semantic_ident(v_item->>'name', 'parameter name');
    IF v_props ? v_name THEN
      PERFORM portal.fn_semantic_raise('GS400', format('duplicate parameter %s', v_name));
    END IF;
    v_type := v_item->>'json_type';
    IF v_type IS NULL OR v_type NOT IN ('string', 'integer', 'number', 'boolean') THEN
      PERFORM portal.fn_semantic_raise('GS400', format('parameter %s needs a type', v_name));
    END IF;
    v_base := jsonb_build_object('type', v_type);
    IF v_type IN ('integer', 'number') THEN
      IF jsonb_typeof(v_item->'minimum') = 'number' THEN
        v_base := v_base || jsonb_build_object('minimum', v_item->'minimum');
      END IF;
      IF jsonb_typeof(v_item->'maximum') = 'number' THEN
        v_base := v_base || jsonb_build_object('maximum', v_item->'maximum');
      END IF;
      IF jsonb_typeof(v_item->'exclusive_minimum') = 'number' THEN
        v_base := v_base || jsonb_build_object('exclusiveMinimum', v_item->'exclusive_minimum');
      END IF;
    END IF;
    v_title := COALESCE(NULLIF(btrim(v_item->>'title'), ''), initcap(replace(v_name, '_', ' ')));
    IF COALESCE((v_item->>'nullable')::boolean, false) THEN
      v_prop := jsonb_build_object(
        'anyOf', jsonb_build_array(v_base, '{"type": "null"}'::jsonb),
        'default', 'null'::jsonb,
        'title', v_title
      );
    ELSE
      v_prop := v_base || jsonb_build_object('title', v_title);
    END IF;
    v_props := v_props || jsonb_build_object(v_name, v_prop);
    IF COALESCE((v_item->>'required')::boolean, false) THEN
      v_required := v_required || to_jsonb(v_name);
    END IF;
  END LOOP;
  v_out := jsonb_build_object('type', 'object', 'additionalProperties', false, 'properties', v_props);
  IF jsonb_array_length(v_required) > 0 THEN
    v_out := v_out || jsonb_build_object('required', v_required);
  END IF;
  IF p_title IS NOT NULL THEN
    v_out := v_out || jsonb_build_object('title', p_title);
  END IF;
  RETURN v_out;
END;
$$;

/* True when the stored params schema round-trips through the list editor unchanged. */
CREATE OR REPLACE FUNCTION portal.fn_semantic_params_editable(p_schema jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  v_rebuilt jsonb;
  v_stored jsonb := COALESCE(p_schema, '{}'::jsonb);
BEGIN
  IF v_stored = '{}'::jsonb THEN
    RETURN true;
  END IF;
  BEGIN
    v_rebuilt := portal.fn_semantic_params_from_list(portal.fn_semantic_params_to_list(v_stored), v_stored->>'title');
  EXCEPTION WHEN OTHERS THEN
    RETURN false;
  END;
  IF NOT (v_stored ? 'required') OR v_stored->'required' = '[]'::jsonb THEN
    v_stored := v_stored - 'required';
  END IF;
  -- required is a set: compare it sorted.
  IF v_stored ? 'required' THEN
    v_stored := jsonb_set(v_stored, '{required}', portal.fn_semantic_sorted_text_array(v_stored->'required'));
  END IF;
  IF v_rebuilt ? 'required' THEN
    v_rebuilt := jsonb_set(v_rebuilt, '{required}', portal.fn_semantic_sorted_text_array(v_rebuilt->'required'));
  END IF;
  RETURN v_rebuilt = v_stored;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_filters_to_list(p_filter jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT COALESCE(jsonb_agg(
    jsonb_strip_nulls(jsonb_build_object(
      'attribute', x->>'attribute', 'op', x->>'op', 'param', x->>'param'
    )) ORDER BY ord
  ), '[]'::jsonb)
  FROM jsonb_array_elements(
    CASE WHEN jsonb_typeof(p_filter->'all_of') = 'array' THEN p_filter->'all_of' ELSE '[]'::jsonb END
  ) WITH ORDINALITY AS t(x, ord);
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_filters_editable(p_filter jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT p_filter IS NULL
      OR p_filter = 'null'::jsonb
      OR p_filter = '{}'::jsonb
      OR (
        (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_filter) k) = ARRAY['all_of']
        AND jsonb_build_object('all_of', portal.fn_semantic_filters_to_list(p_filter)) = p_filter
      );
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_filters_from_list(
  p_entity_id integer,
  p_filters jsonb,
  p_params jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_item jsonb;
  v_attr text;
  v_op text;
  v_param text;
  v_ops text[];
  v_out jsonb := '[]'::jsonb;
BEGIN
  IF p_filters IS NULL OR jsonb_typeof(p_filters) <> 'array' OR jsonb_array_length(p_filters) = 0 THEN
    RETURN NULL;
  END IF;
  FOR v_item IN SELECT * FROM jsonb_array_elements(p_filters)
  LOOP
    v_attr := NULLIF(btrim(v_item->>'attribute'), '');
    v_op := NULLIF(btrim(v_item->>'op'), '');
    v_param := NULLIF(btrim(v_item->>'param'), '');
    IF v_attr IS NULL OR v_op IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS400', 'each filter needs an attribute and an operator');
    END IF;
    SELECT a.filterable_ops INTO v_ops
    FROM portal.semantic_attribute a
    WHERE a.entity_id = p_entity_id AND a.code = v_attr;
    IF NOT FOUND THEN
      PERFORM portal.fn_semantic_raise('GS400', format('attribute %s is not on this entity', v_attr));
    END IF;
    IF NOT (v_op = ANY (v_ops)) THEN
      PERFORM portal.fn_semantic_raise('GS400', format('operator %s is not allowed on %s', v_op, v_attr));
    END IF;
    IF v_op <> 'is_null' THEN
      IF v_param IS NULL THEN
        PERFORM portal.fn_semantic_raise('GS400', format('filter on %s needs a parameter', v_attr));
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(p_params, '[]'::jsonb)) p WHERE p->>'name' = v_param
      ) THEN
        PERFORM portal.fn_semantic_raise('GS400', format('filter parameter %s is not a request parameter', v_param));
      END IF;
      v_out := v_out || jsonb_build_array(jsonb_build_object('attribute', v_attr, 'op', v_op, 'param', v_param));
    ELSE
      v_out := v_out || jsonb_build_array(jsonb_build_object('attribute', v_attr, 'op', v_op));
    END IF;
  END LOOP;
  RETURN jsonb_build_object('all_of', v_out);
END;
$$;

/* Row types: composite types (not table row types) in the portal schema. */
CREATE OR REPLACE FUNCTION portal.fn_semantic_row_type(p_name text)
RETURNS regtype
LANGUAGE sql
STABLE
SET search_path = portal, pg_temp
AS $$
  SELECT t.oid::regtype
  FROM pg_type t
  JOIN pg_namespace n ON n.oid = t.typnamespace
  JOIN pg_class c ON c.oid = t.typrelid
  WHERE n.nspname = 'portal'
    AND c.relkind = 'c'
    AND t.typname = CASE
      WHEN position('.' IN btrim(p_name)) > 0 THEN split_part(btrim(p_name), '.', 2)
      ELSE btrim(p_name)
    END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_row_type_schema(p_row_type regtype)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
  SELECT jsonb_build_object(
    'type', 'object',
    'title', (SELECT t.typname FROM pg_type t WHERE t.oid = p_row_type),
    'properties', COALESCE(jsonb_object_agg(
      a.attname,
      jsonb_build_object('type', CASE
        WHEN a.atttypid IN ('int2'::regtype, 'int4'::regtype, 'int8'::regtype) THEN 'integer'
        WHEN a.atttypid IN ('numeric'::regtype, 'float4'::regtype, 'float8'::regtype) THEN 'number'
        WHEN a.atttypid = 'bool'::regtype THEN 'boolean'
        ELSE 'string'
      END)
    ), '{}'::jsonb)
  )
  FROM pg_type t
  JOIN pg_attribute a ON a.attrelid = t.typrelid AND a.attnum > 0 AND NOT a.attisdropped
  WHERE t.oid = p_row_type;
$$;

/* Function targets the runner can call: name(integer, jsonb, integer), outside system schemas. */
CREATE OR REPLACE FUNCTION portal.fn_semantic_target_function_ok(p_name text)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT btrim(coalesce(p_name, '')) ~ '^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$'
     AND split_part(btrim(p_name), '.', 1) NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
     AND to_regprocedure(btrim(p_name) || '(integer, jsonb, integer)') IS NOT NULL;
$$;

CREATE OR REPLACE FUNCTION portal.fn_semantic_template_targets()
RETURNS text[]
LANGUAGE sql
IMMUTABLE
AS $$
  -- Template targets sp_run_semantic_request implements (keep in step with the runner).
  SELECT ARRAY['portal.fn_semantic_core_filter_organizations']::text[];
$$;

-- ── Namespaces ────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_list_namespaces_editor(p_session_token text)
RETURNS TABLE (code text, display_name text, owner_app text, entity_count integer, request_count integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/semantic/namespaces']);
  RETURN QUERY
  SELECT n.code, n.display_name, n.owner_app,
         (SELECT count(*)::int FROM portal.semantic_entity e WHERE e.namespace = n.code),
         (SELECT count(*)::int FROM portal.semantic_request r WHERE r.namespace = n.code)
  FROM portal.semantic_namespace n
  ORDER BY n.code;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_get_namespace(p_session_token text, p_code text)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v jsonb;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/semantic/namespaces']);
  SELECT jsonb_build_object('code', n.code, 'display_name', n.display_name, 'owner_app', n.owner_app)
  INTO v FROM portal.semantic_namespace n WHERE n.code = p_code;
  IF v IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic namespace not found');
  END IF;
  RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_save_namespace(
  p_session_token text,
  p_code text,
  p_doc jsonb
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_code text := COALESCE(NULLIF(btrim(p_code), ''), portal.fn_semantic_ident(p_doc->>'code', 'namespace code'));
  v_display text := COALESCE(portal.fn_doc_text(p_doc, 'display_name'), v_code);
  v_owner text := COALESCE(
    portal.fn_doc_text(p_doc, 'owner_app'),
    (SELECT n.owner_app FROM portal.semantic_namespace n WHERE n.code = btrim(p_code)),
    'goliath_app'
  );
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/namespaces', v_code) LIMIT 1;
  IF p_code IS NOT NULL AND NOT EXISTS (SELECT 1 FROM portal.semantic_namespace n WHERE n.code = v_code) THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic namespace not found');
  END IF;
  IF p_code IS NULL AND EXISTS (SELECT 1 FROM portal.semantic_namespace n WHERE n.code = v_code) THEN
    PERFORM portal.fn_semantic_raise('GS409', format('namespace %s already exists', v_code));
  END IF;
  INSERT INTO portal.semantic_namespace (code, display_name, owner_app)
  VALUES (v_code, v_display, v_owner)
  ON CONFLICT (code) DO UPDATE SET display_name = EXCLUDED.display_name, owner_app = EXCLUDED.owner_app;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'semantic_namespace',
    CASE WHEN p_code IS NULL THEN 'create' ELSE 'update' END, v_code,
    jsonb_build_object('display_name', v_display, 'owner_app', v_owner)
  );
  RETURN v_code;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_delete_namespace(p_session_token text, p_code text)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/namespaces', p_code) LIMIT 1;
  PERFORM 1 FROM portal.semantic_namespace n WHERE n.code = p_code FOR UPDATE;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic namespace not found');
  END IF;
  IF EXISTS (SELECT 1 FROM portal.semantic_entity e WHERE e.namespace = p_code)
     OR EXISTS (SELECT 1 FROM portal.semantic_request r WHERE r.namespace = p_code) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'namespace still has entities or requests; delete those first');
  END IF;
  DELETE FROM portal.semantic_namespace n WHERE n.code = p_code;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'semantic_namespace', 'delete', p_code, '{}'::jsonb
  );
  RETURN 'deleted';
END;
$$;

-- ── Entities ──────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_list_entities_editor(p_session_token text)
RETURNS TABLE (
  id integer, namespace text, code text, display_name text, description text,
  meta_class_name text, storage_relation text, attribute_count integer, request_count integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/semantic/entities']);
  RETURN QUERY
  SELECT e.id, e.namespace, e.code, e.display_name, e.description,
         c."Name"::text, e.storage_relation,
         (SELECT count(*)::int FROM portal.semantic_attribute a WHERE a.entity_id = e.id),
         (SELECT count(*)::int FROM portal.semantic_request r WHERE r.entity_id = e.id)
  FROM portal.semantic_entity e
  LEFT JOIN "Meta"."Classes" c ON c."ID" = e.meta_class_id
  ORDER BY e.namespace, e.code;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_get_entity(p_session_token text, p_id integer)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v jsonb;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/semantic/entities']);
  SELECT jsonb_strip_nulls(jsonb_build_object(
    'id', e.id, 'namespace', e.namespace, 'code', e.code, 'display_name', e.display_name,
    'description', e.description, 'meta_class_name', c."Name", 'storage_relation', e.storage_relation
  ))
  INTO v
  FROM portal.semantic_entity e
  LEFT JOIN "Meta"."Classes" c ON c."ID" = e.meta_class_id
  WHERE e.id = p_id;
  IF v IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic entity not found');
  END IF;
  RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_save_entity(
  p_session_token text,
  p_id integer,
  p_doc jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_row portal.semantic_entity%ROWTYPE;
  v_ns text;
  v_code text;
  v_display text := portal.fn_doc_text(p_doc, 'display_name');
  v_desc text := COALESCE(p_doc->>'description', '');
  v_storage text := portal.fn_doc_text(p_doc, 'storage_relation');
  v_meta text := portal.fn_doc_text(p_doc, 'meta_class_name');
  v_id integer;
BEGIN
  IF p_id IS NOT NULL THEN
    SELECT * INTO v_row FROM portal.semantic_entity e WHERE e.id = p_id FOR UPDATE;
    IF NOT FOUND THEN
      PERFORM portal.fn_semantic_raise('GS404', 'semantic entity not found');
    END IF;
    v_ns := v_row.namespace;
  ELSE
    v_ns := portal.fn_doc_text(p_doc, 'namespace');
    IF v_ns IS NULL OR NOT EXISTS (SELECT 1 FROM portal.semantic_namespace n WHERE n.code = v_ns) THEN
      PERFORM portal.fn_semantic_raise('GS400', 'pick an existing namespace');
    END IF;
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/entities', v_ns) LIMIT 1;

  IF v_storage IS NOT NULL AND to_regclass(v_storage) IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', format('storage relation %s does not exist', v_storage));
  END IF;

  IF p_id IS NULL THEN
    v_code := portal.fn_semantic_ident(p_doc->>'code', 'entity code');
    IF v_display IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS400', 'display name is required');
    END IF;
    IF EXISTS (SELECT 1 FROM portal.semantic_entity e WHERE e.namespace = v_ns AND e.code = v_code) THEN
      PERFORM portal.fn_semantic_raise('GS409', format('entity %s.%s already exists', v_ns, v_code));
    END IF;
    -- Existing writer: Meta class binding and sync included.
    SELECT r.entity_id INTO v_id
    FROM portal.sp_session_semantic_register_entity(p_session_token, v_ns, v_code, v_display, v_desc, v_meta) r;
    UPDATE portal.semantic_entity SET storage_relation = v_storage WHERE id = v_id;
  ELSE
    IF p_doc ? 'meta_class_name'
       AND v_meta IS DISTINCT FROM (SELECT c."Name"::text FROM "Meta"."Classes" c WHERE c."ID" = v_row.meta_class_id) THEN
      PERFORM portal.fn_semantic_raise('GS409', 'the Meta class mapping is changed in the Meta model, not here');
    END IF;
    UPDATE portal.semantic_entity
    SET display_name = COALESCE(v_display, v_row.display_name),
        description = v_desc,
        storage_relation = v_storage
    WHERE id = p_id;
    v_id := p_id;
  END IF;

  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'semantic_entity',
    CASE WHEN p_id IS NULL THEN 'create' ELSE 'update' END, v_id::text,
    jsonb_strip_nulls(jsonb_build_object('namespace', v_ns, 'display_name', v_display, 'storage_relation', v_storage))
  );
  RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_delete_entity(p_session_token text, p_id integer)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, wf, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_row portal.semantic_entity%ROWTYPE;
BEGIN
  SELECT * INTO v_row FROM portal.semantic_entity e WHERE e.id = p_id FOR UPDATE;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic entity not found');
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/entities', v_row.namespace) LIMIT 1;
  IF v_row.meta_class_id IS NOT NULL THEN
    PERFORM portal.fn_semantic_raise('GS409', 'entity is mapped to a Meta class; it is removed with the class mapping');
  END IF;
  IF EXISTS (SELECT 1 FROM portal.semantic_request r WHERE r.entity_id = p_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'entity still has requests; delete them first');
  END IF;
  IF EXISTS (SELECT 1 FROM wf.workflow_action a WHERE a.semantic_entity_id = p_id)
     OR EXISTS (SELECT 1 FROM portal.semantic_action_binding b WHERE b.entity_id = p_id)
     OR EXISTS (SELECT 1 FROM portal.semantic_nav_binding nb WHERE nb.entity_id = p_id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'entity is bound to actions or navigation');
  END IF;
  -- Attributes are part of the entity definition (ON DELETE CASCADE).
  DELETE FROM portal.semantic_entity e WHERE e.id = p_id;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'semantic_entity', 'delete', p_id::text,
    jsonb_build_object('namespace', v_row.namespace, 'code', v_row.code)
  );
  RETURN 'deleted';
END;
$$;

-- ── Attributes ────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_list_attributes_editor(p_session_token text)
RETURNS TABLE (
  id integer, entity_id integer, entity text, code text, column_name text,
  json_type text, role text, filterable_ops text[]
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/semantic/attributes']);
  RETURN QUERY
  SELECT a.id, a.entity_id, e.namespace || '.' || e.code, a.code, a.column_name, a.json_type, a.role, a.filterable_ops
  FROM portal.semantic_attribute a
  JOIN portal.semantic_entity e ON e.id = a.entity_id
  ORDER BY e.namespace, e.code, a.code;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_get_attribute(p_session_token text, p_id integer)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v jsonb;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/semantic/attributes']);
  SELECT jsonb_build_object(
    'id', a.id, 'entity_id', a.entity_id, 'code', a.code, 'column_name', a.column_name,
    'json_type', a.json_type, 'role', a.role, 'filterable_ops', to_jsonb(a.filterable_ops)
  )
  INTO v FROM portal.semantic_attribute a WHERE a.id = p_id;
  IF v IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic attribute not found');
  END IF;
  RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_save_attribute(
  p_session_token text,
  p_id integer,
  p_doc jsonb
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_row portal.semantic_attribute%ROWTYPE;
  v_entity_id integer;
  v_ns text;
  v_code text;
  v_column text := btrim(coalesce(p_doc->>'column_name', ''));
  v_type text := portal.fn_doc_text(p_doc, 'json_type');
  v_role text := portal.fn_doc_text(p_doc, 'role');
  v_ops text[];
  v_id integer;
BEGIN
  IF p_id IS NOT NULL THEN
    SELECT * INTO v_row FROM portal.semantic_attribute a WHERE a.id = p_id FOR UPDATE;
    IF NOT FOUND THEN
      PERFORM portal.fn_semantic_raise('GS404', 'semantic attribute not found');
    END IF;
    v_entity_id := v_row.entity_id;
    v_code := v_row.code;
  ELSE
    v_entity_id := NULLIF(p_doc->>'entity_id', '')::integer;
    v_code := portal.fn_semantic_ident(p_doc->>'code', 'attribute code');
  END IF;
  SELECT e.namespace INTO v_ns FROM portal.semantic_entity e WHERE e.id = v_entity_id;
  IF v_ns IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'pick an existing entity');
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/attributes', v_ns) LIMIT 1;

  IF v_column !~ '^[A-Za-z_][A-Za-z0-9_]{0,62}$' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'column name must be letters, digits and underscores');
  END IF;
  IF v_type IS NULL OR v_type NOT IN ('string', 'integer', 'number', 'boolean') THEN
    PERFORM portal.fn_semantic_raise('GS400', 'type must be string, integer, number or boolean');
  END IF;
  IF v_role IS NULL OR v_role NOT IN ('list', 'detail', 'filter', 'key') THEN
    PERFORM portal.fn_semantic_raise('GS400', 'role must be list, detail, filter or key');
  END IF;
  SELECT COALESCE(array_agg(DISTINCT o ORDER BY o), ARRAY[]::text[]) INTO v_ops
  FROM jsonb_array_elements_text(
    CASE WHEN jsonb_typeof(p_doc->'filterable_ops') = 'array' THEN p_doc->'filterable_ops' ELSE '[]'::jsonb END
  ) o;
  IF EXISTS (SELECT 1 FROM unnest(v_ops) o WHERE o NOT IN ('eq', 'gte', 'lte', 'starts_with', 'is_null')) THEN
    PERFORM portal.fn_semantic_raise('GS400', 'operators must be eq, gte, lte, starts_with or is_null');
  END IF;

  IF p_id IS NULL THEN
    IF EXISTS (SELECT 1 FROM portal.semantic_attribute a WHERE a.entity_id = v_entity_id AND a.code = v_code) THEN
      PERFORM portal.fn_semantic_raise('GS409', format('attribute %s already exists on this entity', v_code));
    END IF;
    INSERT INTO portal.semantic_attribute (entity_id, code, column_name, json_type, role, filterable_ops)
    VALUES (v_entity_id, v_code, v_column, v_type, v_role, v_ops)
    RETURNING id INTO v_id;
  ELSE
    -- Removing an operator a request filter uses would break that request.
    IF EXISTS (
      SELECT 1
      FROM portal.semantic_request r,
           jsonb_array_elements(
             CASE WHEN jsonb_typeof(r.filter_template->'all_of') = 'array' THEN r.filter_template->'all_of' ELSE '[]'::jsonb END
           ) f
      WHERE r.entity_id = v_entity_id AND f->>'attribute' = v_code AND NOT ((f->>'op') = ANY (v_ops))
    ) THEN
      PERFORM portal.fn_semantic_raise('GS409', 'a request filter uses an operator you removed');
    END IF;
    UPDATE portal.semantic_attribute
    SET column_name = v_column, json_type = v_type, role = v_role, filterable_ops = v_ops
    WHERE id = p_id;
    v_id := p_id;
  END IF;

  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'semantic_attribute',
    CASE WHEN p_id IS NULL THEN 'create' ELSE 'update' END, v_id::text,
    jsonb_build_object('entity_id', v_entity_id, 'code', v_code, 'role', v_role)
  );
  RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_delete_attribute(p_session_token text, p_id integer)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_row portal.semantic_attribute%ROWTYPE;
  v_ns text;
BEGIN
  SELECT * INTO v_row FROM portal.semantic_attribute a WHERE a.id = p_id FOR UPDATE;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic attribute not found');
  END IF;
  SELECT e.namespace INTO v_ns FROM portal.semantic_entity e WHERE e.id = v_row.entity_id;
  SELECT * INTO v_ctx FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/attributes', v_ns) LIMIT 1;
  IF EXISTS (
    SELECT 1
    FROM portal.semantic_request r,
         jsonb_array_elements(
           CASE WHEN jsonb_typeof(r.filter_template->'all_of') = 'array' THEN r.filter_template->'all_of' ELSE '[]'::jsonb END
         ) f
    WHERE r.entity_id = v_row.entity_id AND f->>'attribute' = v_row.code
  ) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'a request filter uses this attribute');
  END IF;
  DELETE FROM portal.semantic_attribute a WHERE a.id = p_id;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'semantic_attribute', 'delete', p_id::text,
    jsonb_build_object('entity_id', v_row.entity_id, 'code', v_row.code)
  );
  RETURN 'deleted';
END;
$$;

-- ── Requests ──────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_list_requests_editor(p_session_token text)
RETURNS TABLE (
  request_code text, version text, namespace text, entity text, target_kind text,
  target_name text, row_type text, required_permission text, max_rows integer, status text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/semantic/requests']);
  RETURN QUERY
  SELECT r.request_code, r.version, r.namespace, e.namespace || '.' || e.code, r.target_kind,
         r.target_name, r.row_type::text, r.required_permission, r.max_rows, r.status
  FROM portal.semantic_request r
  JOIN portal.semantic_entity e ON e.id = r.entity_id
  ORDER BY r.namespace, r.request_code, r.version;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_get_request(
  p_session_token text,
  p_request_code text,
  p_version text
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_req portal.semantic_request%ROWTYPE;
BEGIN
  PERFORM portal.fn_session_require_any_nav(p_session_token, ARRAY['/app/semantic/requests']);
  SELECT * INTO v_req FROM portal.semantic_request r WHERE r.request_code = p_request_code AND r.version = p_version;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic request not found');
  END IF;
  RETURN jsonb_strip_nulls(jsonb_build_object(
    'request_code', v_req.request_code,
    'version', v_req.version,
    'namespace', v_req.namespace,
    'entity_id', v_req.entity_id,
    'target_kind', v_req.target_kind,
    'target_name', v_req.target_name,
    'row_type', (SELECT t.typname FROM pg_type t WHERE t.oid = v_req.row_type),
    'required_permission', v_req.required_permission,
    'max_rows', v_req.max_rows,
    'status', v_req.status,
    'params', portal.fn_semantic_params_to_list(v_req.params_schema),
    'params_editable', portal.fn_semantic_params_editable(v_req.params_schema),
    'filters', portal.fn_semantic_filters_to_list(v_req.filter_template),
    'filters_editable', portal.fn_semantic_filters_editable(v_req.filter_template)
  ));
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_save_request(
  p_session_token text,
  p_key_code text,
  p_key_version text,
  p_doc jsonb
)
RETURNS TABLE (request_code text, version text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_old portal.semantic_request%ROWTYPE;
  v_is_new boolean := p_key_code IS NULL;
  v_code text;
  v_version text;
  v_ns text := portal.fn_doc_text(p_doc, 'namespace');
  v_entity_id integer := NULLIF(p_doc->>'entity_id', '')::integer;
  v_kind text := portal.fn_doc_text(p_doc, 'target_kind');
  v_target text := portal.fn_doc_text(p_doc, 'target_name');
  v_row_type regtype := portal.fn_semantic_row_type(portal.fn_doc_text(p_doc, 'row_type'));
  v_perm text := portal.fn_doc_text(p_doc, 'required_permission');
  v_max integer := COALESCE(NULLIF(p_doc->>'max_rows', '')::integer, 500);
  v_params jsonb := CASE WHEN jsonb_typeof(p_doc->'params') = 'array' THEN p_doc->'params' ELSE '[]'::jsonb END;
  v_filters jsonb := CASE WHEN jsonb_typeof(p_doc->'filters') = 'array' THEN p_doc->'filters' ELSE '[]'::jsonb END;
  v_params_schema jsonb;
  v_result_schema jsonb;
  v_filter jsonb;
  v_row_type_name text;
  v_hash text;
  v_base_ns text;
BEGIN
  IF v_is_new THEN
    v_code := btrim(coalesce(p_doc->>'request_code', ''));
    IF v_code !~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$' THEN
      PERFORM portal.fn_semantic_raise('GS400', 'request code must look like namespace.name');
    END IF;
    v_version := COALESCE(portal.fn_doc_text(p_doc, 'version'), '1');
    IF EXISTS (SELECT 1 FROM portal.semantic_request r WHERE r.request_code = v_code AND r.version = v_version) THEN
      PERFORM portal.fn_semantic_raise('GS409', format('request %s v%s already exists', v_code, v_version));
    END IF;
  ELSE
    SELECT * INTO v_old FROM portal.semantic_request r
    WHERE r.request_code = p_key_code AND r.version = p_key_version FOR UPDATE;
    IF NOT FOUND THEN
      PERFORM portal.fn_semantic_raise('GS404', 'semantic request not found');
    END IF;
    v_code := v_old.request_code;
    v_version := v_old.version;
    -- The namespace is part of the request's identity; editing it here would move ownership.
    v_ns := v_old.namespace;
    -- Gate on the stored namespace before anything else.
    PERFORM 1 FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/requests', v_old.namespace);
  END IF;

  IF v_ns IS NULL OR NOT EXISTS (SELECT 1 FROM portal.semantic_namespace n WHERE n.code = v_ns) THEN
    PERFORM portal.fn_semantic_raise('GS400', 'pick an existing namespace');
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/requests', v_ns) LIMIT 1;

  IF v_entity_id IS NULL OR NOT EXISTS (SELECT 1 FROM portal.semantic_entity e WHERE e.id = v_entity_id) THEN
    PERFORM portal.fn_semantic_raise('GS400', 'pick an existing entity');
  END IF;
  IF v_row_type IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'pick a row type (a portal composite type)');
  END IF;
  IF v_kind = 'function' THEN
    IF NOT portal.fn_semantic_target_function_ok(v_target) THEN
      PERFORM portal.fn_semantic_raise('GS400', 'target must be an existing schema.function(integer, jsonb, integer)');
    END IF;
  ELSIF v_kind = 'template' THEN
    IF v_target IS NULL OR NOT (v_target = ANY (portal.fn_semantic_template_targets())) THEN
      PERFORM portal.fn_semantic_raise('GS400', 'target must be a template the runner implements');
    END IF;
  ELSE
    PERFORM portal.fn_semantic_raise('GS400', 'target kind must be function or template');
  END IF;
  IF v_max < 1 OR v_max > portal.fn_semantic_max_rows() THEN
    PERFORM portal.fn_semantic_raise('GS400', format('max rows must be between 1 and %s', portal.fn_semantic_max_rows()));
  END IF;

  -- Parameters: unrepresentable stored schemas are kept verbatim and may not be changed here.
  IF NOT v_is_new AND NOT portal.fn_semantic_params_editable(v_old.params_schema) THEN
    IF portal.fn_semantic_param_list_norm(v_params)
       <> portal.fn_semantic_param_list_norm(portal.fn_semantic_params_to_list(v_old.params_schema)) THEN
      PERFORM portal.fn_semantic_raise('GS409', 'this request''s parameters are maintained in its seed');
    END IF;
    v_params_schema := v_old.params_schema;
  ELSE
    v_params_schema := portal.fn_semantic_params_from_list(
      v_params, CASE WHEN v_is_new THEN NULL ELSE v_old.params_schema->>'title' END
    );
  END IF;

  IF NOT v_is_new AND NOT portal.fn_semantic_filters_editable(v_old.filter_template) THEN
    IF portal.fn_semantic_filter_list_norm(v_filters)
       <> portal.fn_semantic_filter_list_norm(portal.fn_semantic_filters_to_list(v_old.filter_template)) THEN
      PERFORM portal.fn_semantic_raise('GS409', 'this request''s filters are maintained in its seed');
    END IF;
    v_filter := v_old.filter_template;
  ELSE
    v_filter := portal.fn_semantic_filters_from_list(v_entity_id, v_filters, portal.fn_semantic_params_to_list(v_params_schema));
  END IF;
  IF v_filter IS NOT NULL AND v_kind = 'function' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'function targets do not take filters');
  END IF;

  IF NOT v_is_new AND v_old.row_type = v_row_type THEN
    v_result_schema := v_old.result_schema;
  ELSE
    v_result_schema := portal.fn_semantic_row_type_schema(v_row_type);
  END IF;

  IF v_perm IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'pick a required permission (requests without one cannot run)');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM portal.security_role_permission_cache c WHERE c.permission_name = v_perm
  ) THEN
    PERFORM portal.fn_semantic_raise('GS400', format('permission %s is not granted to any role', v_perm));
  END IF;

  SELECT t.typname::text INTO v_row_type_name FROM pg_type t WHERE t.oid = v_row_type;
  v_hash := md5(concat_ws('|', v_code, v_version, v_target, v_params_schema::text, v_result_schema::text,
                          coalesce(v_filter::text, '')));
  v_base_ns := CASE WHEN v_is_new THEN NULL ELSE v_old.base_namespace END;
  CALL portal.sp_semantic_register_request(
    v_code, v_version, v_ns, v_entity_id, v_kind, v_target, v_row_type_name,
    v_params_schema, v_result_schema, v_hash, v_filter, v_perm, v_max, v_base_ns
  );

  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'semantic_request',
    CASE WHEN v_is_new THEN 'create' ELSE 'update' END, v_code || '@' || v_version,
    jsonb_strip_nulls(jsonb_build_object('target_kind', v_kind, 'target_name', v_target, 'required_permission', v_perm))
  );
  RETURN QUERY SELECT v_code, v_version;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_set_request_status(
  p_session_token text,
  p_request_code text,
  p_version text,
  p_status text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_ns text;
BEGIN
  IF p_status NOT IN ('ACTIVE', 'RETIRED') THEN
    PERFORM portal.fn_semantic_raise('GS400', 'status must be ACTIVE or RETIRED');
  END IF;
  SELECT r.namespace INTO v_ns FROM portal.semantic_request r
  WHERE r.request_code = p_request_code AND r.version = p_version FOR UPDATE;
  IF v_ns IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic request not found');
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/requests', v_ns) LIMIT 1;
  UPDATE portal.semantic_request r SET status = p_status
  WHERE r.request_code = p_request_code AND r.version = p_version;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'semantic_request',
    CASE WHEN p_status = 'RETIRED' THEN 'retire' ELSE 'activate' END, p_request_code || '@' || p_version, '{}'::jsonb
  );
  RETURN p_status;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_delete_request(
  p_session_token text,
  p_request_code text,
  p_version text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_req portal.semantic_request%ROWTYPE;
BEGIN
  SELECT * INTO v_req FROM portal.semantic_request r
  WHERE r.request_code = p_request_code AND r.version = p_version FOR UPDATE;
  IF NOT FOUND THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic request not found');
  END IF;
  SELECT * INTO v_ctx FROM portal.fn_semantic_editor_require(p_session_token, '/app/semantic/requests', v_req.namespace) LIMIT 1;
  IF v_req.status <> 'RETIRED' THEN
    PERFORM portal.fn_semantic_raise('GS409', 'retire the request before deleting it');
  END IF;
  IF EXISTS (SELECT 1 FROM portal.semantic_nav_binding nb WHERE nb.request_id = v_req.id) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'request is bound to navigation');
  END IF;
  DELETE FROM portal.semantic_request r WHERE r.id = v_req.id;
  PERFORM portal.fn_record_editor_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'semantic_request', 'delete',
    p_request_code || '@' || p_version, '{}'::jsonb
  );
  RETURN 'deleted';
END;
$$;
