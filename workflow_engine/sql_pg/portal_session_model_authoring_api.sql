/*
  Session-bound platform model authoring (Meta classes, semantic registry, NavTree, RBAC).
  Callable by goliath_portal only. Requires platform.model.author (+ meta.schema.read).
*/

CREATE TABLE IF NOT EXISTS portal.model_authoring_audit (
  audit_id bigserial PRIMARY KEY,
  session_id integer NOT NULL,
  user_id integer NOT NULL,
  scope_id integer NULL,
  action_code text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

DO $perm$
DECLARE
  v_class_id int;
  v_obj_id int;
  v_op_id int;
BEGIN
  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = 'portal/NavNode' LIMIT 1;
  IF v_class_id IS NULL THEN
    RETURN;
  END IF;
  SELECT o."ID" INTO v_obj_id FROM "Meta"."Objs" o ORDER BY o."ID" LIMIT 1;
  IF v_obj_id IS NULL THEN
    INSERT INTO "Meta"."Objs" ("ClassID") VALUES (v_class_id) RETURNING "ID" INTO v_obj_id;
  END IF;
  SELECT op."ID" INTO v_op_id
  FROM "Meta"."Operations" op
  WHERE op."Name" = 'meta.permission_anchor'
  LIMIT 1;
  IF v_op_id IS NULL THEN
    INSERT INTO "Meta"."Operations" ("Name", "ClassID")
    VALUES ('meta.permission_anchor', v_class_id)
    RETURNING "ID" INTO v_op_id;
  END IF;
  INSERT INTO "RBAC"."Permissions" ("Name", "ObjID", "OperationID")
  SELECT 'platform.model.author', v_obj_id, v_op_id
  WHERE NOT EXISTS (
    SELECT 1 FROM "RBAC"."Permissions" p WHERE p."Name" = 'platform.model.author'
  );
END
$perm$;

CREATE OR REPLACE FUNCTION portal.fn_session_model_author_require(
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
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
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
    PERFORM portal.fn_semantic_raise('GS403', 'active scope required for model authoring');
  END IF;

  IF NOT portal.fn_semantic_session_has_permission(v_sess.user_id, 'meta.schema.read') THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied');
  END IF;

  IF NOT portal.fn_semantic_session_has_permission(v_sess.user_id, 'platform.model.author') THEN
    PERFORM portal.fn_semantic_raise('GS403', 'platform model author permission denied');
  END IF;

  IF p_node_path IS NOT NULL AND btrim(p_node_path) <> '' THEN
    PERFORM portal.fn_session_operator_require(p_session_token, p_node_path);
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_model_author_audit(
  p_session_id int,
  p_user_id int,
  p_scope_id int,
  p_action text,
  p_payload jsonb
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  INSERT INTO portal.model_authoring_audit (session_id, user_id, scope_id, action_code, payload)
  VALUES (p_session_id, p_user_id, p_scope_id, p_action, COALESCE(p_payload, '{}'::jsonb));
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_class_create(
  p_session_token text,
  p_class_name text,
  p_parent_class_name text DEFAULT NULL
)
RETURNS TABLE (class_id integer, class_name text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_parent_id int;
  v_new_id int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/meta/classes') LIMIT 1;

  IF p_class_name IS NULL OR btrim(p_class_name) = '' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'class_name required');
  END IF;
  IF EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = btrim(p_class_name)) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'meta class already exists');
  END IF;

  v_parent_id := NULL;
  IF p_parent_class_name IS NOT NULL AND btrim(p_parent_class_name) <> '' THEN
    SELECT c."ID" INTO v_parent_id
    FROM "Meta"."Classes" c
    WHERE c."Name" = btrim(p_parent_class_name);
    IF v_parent_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'parent meta class not found');
    END IF;
  END IF;

  INSERT INTO "Meta"."Classes" ("Name", "ParentID")
  VALUES (btrim(p_class_name), v_parent_id)
  RETURNING "ID" INTO v_new_id;

  PERFORM "Meta".sp_refresh_class_hierarchy(v_new_id);
  PERFORM "Meta".sp_meta_publish_class_type(v_new_id, false);
  PERFORM "Meta".sp_class_regenerate_views(v_new_id);

  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'meta.class.create',
    jsonb_build_object('class_name', btrim(p_class_name), 'parent', p_parent_class_name)
  );

  RETURN QUERY SELECT v_new_id, btrim(p_class_name)::text;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_field_upsert(
  p_session_token text,
  p_class_name text,
  p_field_name text,
  p_type_name text,
  p_type_version text DEFAULT '1.0',
  p_required boolean DEFAULT false
)
RETURNS TABLE (field_id integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
  v_type_id bigint;
  v_field_id int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/meta/fields') LIMIT 1;

  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = btrim(p_class_name);
  IF v_class_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta class not found');
  END IF;

  SELECT t.id INTO v_type_id
  FROM wf.data_type t
  WHERE t.name = btrim(p_type_name) AND t.version = COALESCE(NULLIF(btrim(p_type_version), ''), '1.0')
  ORDER BY t.id DESC
  LIMIT 1;
  IF v_type_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'wf.data_type not found');
  END IF;

  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
  VALUES (v_class_id, btrim(p_field_name), v_type_id, COALESCE(p_required, false))
  ON CONFLICT ON CONSTRAINT "UQ_Meta_Fields_Class_Name"
  DO UPDATE SET "TypeID" = EXCLUDED."TypeID", "Required" = EXCLUDED."Required"
  RETURNING "ID" INTO v_field_id;

  PERFORM "Meta".sp_meta_publish_class_type(v_class_id, false);
  PERFORM "Meta".sp_class_regenerate_views(v_class_id);

  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'meta.field.upsert',
    jsonb_build_object(
      'class_name', p_class_name,
      'field_name', p_field_name,
      'type_name', p_type_name,
      'required', p_required
    )
  );

  RETURN QUERY SELECT v_field_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_field_retire(
  p_session_token text,
  p_class_name text,
  p_field_name text
)
RETURNS TABLE (ok boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/meta/fields') LIMIT 1;
  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = btrim(p_class_name);
  IF v_class_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta class not found');
  END IF;
  DELETE FROM "Meta"."Fields" f
  WHERE f."ClassID" = v_class_id AND f."Name" = btrim(p_field_name);

  PERFORM "Meta".sp_meta_publish_class_type(v_class_id, false);
  PERFORM "Meta".sp_class_regenerate_views(v_class_id);
  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'meta.field.retire',
    jsonb_build_object('class_name', p_class_name, 'field_name', p_field_name)
  );
  RETURN QUERY SELECT true;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_register_entity(
  p_session_token text,
  p_namespace text,
  p_code text,
  p_display_name text,
  p_description text DEFAULT '',
  p_meta_class_name text DEFAULT NULL
)
RETURNS TABLE (entity_id integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_meta_class_id int;
  v_entity_id int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/semantic/entities') LIMIT 1;

  v_meta_class_id := NULL;
  IF p_meta_class_name IS NOT NULL AND btrim(p_meta_class_name) <> '' THEN
    SELECT c."ID" INTO v_meta_class_id FROM "Meta"."Classes" c WHERE c."Name" = btrim(p_meta_class_name);
    IF v_meta_class_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'meta class not found');
    END IF;
  END IF;

  CALL portal.sp_semantic_register_entity(
    btrim(p_namespace),
    btrim(p_code),
    btrim(p_display_name),
    COALESCE(p_description, ''),
  'urn:goliath:semantic:entity/' || btrim(p_namespace) || '/' || btrim(p_code),
    '1',
    '',
    NULL,
    v_meta_class_id
  );

  IF v_meta_class_id IS NOT NULL THEN
    v_entity_id := "Meta".sp_semantic_sync_class_entity(
      v_meta_class_id,
      btrim(p_namespace),
      btrim(p_code),
      btrim(p_display_name),
      COALESCE(p_description, '')
    );
  ELSE
    SELECT e.id INTO v_entity_id
    FROM portal.semantic_entity e
    WHERE e.namespace = btrim(p_namespace) AND e.code = btrim(p_code);
  END IF;

  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'semantic.entity.register',
    jsonb_build_object(
      'namespace', p_namespace,
      'code', p_code,
      'meta_class_name', p_meta_class_name
    )
  );

  RETURN QUERY SELECT v_entity_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_semantic_register_attribute(
  p_session_token text,
  p_entity_id integer,
  p_code text,
  p_column_name text,
  p_json_type text,
  p_role text DEFAULT 'dimension',
  p_filterable_ops text[] DEFAULT ARRAY['eq']::text[]
)
RETURNS TABLE (ok boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/semantic/attributes') LIMIT 1;

  IF NOT EXISTS (SELECT 1 FROM portal.semantic_entity e WHERE e.id = p_entity_id) THEN
    PERFORM portal.fn_semantic_raise('GS404', 'semantic entity not found');
  END IF;

  CALL portal.sp_semantic_register_attribute(
    p_entity_id, btrim(p_code), btrim(p_column_name), btrim(p_json_type), btrim(p_role), p_filterable_ops
  );

  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'semantic.attribute.register',
    jsonb_build_object('entity_id', p_entity_id, 'code', p_code)
  );

  RETURN QUERY SELECT true;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_nav_register_node(
  p_session_token text,
  p_parent_nav_id integer,
  p_caption text,
  p_seq smallint,
  p_node_path text DEFAULT NULL
)
RETURNS TABLE (node_id integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_node int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/admin/navigation') LIMIT 1;

  SELECT portal.sp_nav_register_node(
    p_parent_nav_id, btrim(p_caption), p_seq, NULL, p_node_path, NULL
  ) INTO v_node;

  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'nav.register',
    jsonb_build_object('caption', p_caption, 'node_path', p_node_path, 'node_id', v_node)
  );

  RETURN QUERY SELECT v_node;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_grant_role_nav_node(
  p_session_token text,
  p_role_id integer,
  p_node_id integer
)
RETURNS TABLE (ok boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_scope int;
  v_ok boolean;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/admin/roles') LIMIT 1;
  v_scope := v_ctx.active_scope_id;

  SELECT g.ok INTO v_ok
  FROM portal.sp_grant_role_nav_node(p_role_id, p_node_id, v_scope) g;

  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'rbac.grant_role_nav',
    jsonb_build_object('role_id', p_role_id, 'node_id', p_node_id)
  );

  RETURN QUERY SELECT COALESCE(v_ok, false);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_grant_user_role_scoped(
  p_session_token text,
  p_target_user_id integer,
  p_role_id integer
)
RETURNS TABLE (inserted boolean, grant_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/admin/users') LIMIT 1;

  RETURN QUERY
  SELECT g.inserted, g.grant_id
  FROM portal.sp_grant_user_role(p_target_user_id, p_role_id, 'SCOPED', v_ctx.active_scope_id, NULL) g;

  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'rbac.grant_user_role',
    jsonb_build_object('target_user_id', p_target_user_id, 'role_id', p_role_id)
  );
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_export_model_package(
  p_session_token text,
  p_class_prefix text DEFAULT ''
)
RETURNS TABLE (package_sql text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_lines text := '';
  v_rec record;
  v_prefix text := COALESCE(NULLIF(btrim(p_class_prefix), ''), 'your_app/');
BEGIN
  PERFORM portal.fn_session_model_author_require(p_session_token, '/app/meta/classes');

  v_lines := v_lines || E'-- GoliathApp model package export (idempotent snippets)\n';
  v_lines := v_lines || format(E'-- Prefix filter: %s\n\n', v_prefix);

  FOR v_rec IN
    SELECT c."Name" AS class_name, p."Name" AS parent_name
    FROM "Meta"."Classes" c
    LEFT JOIN "Meta"."Classes" p ON p."ID" = c."ParentID"
    WHERE c."Name" LIKE v_prefix || '%'
    ORDER BY c."Name"
  LOOP
    v_lines := v_lines || format(
      E'INSERT INTO "Meta"."Classes" ("Name", "ParentID")\n'
      || E'SELECT %L, (SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = %L LIMIT 1)\n'
      || E'WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Classes" WHERE "Name" = %L);\n\n',
      v_rec.class_name,
      v_rec.parent_name,
      v_rec.class_name
    );
  END LOOP;

  FOR v_rec IN
    SELECT c."Name" AS class_name, f."Name" AS field_name, t.name AS type_name, t.version, f."Required"
    FROM "Meta"."Fields" f
    JOIN "Meta"."Classes" c ON c."ID" = f."ClassID"
    JOIN wf.data_type t ON t.id = f."TypeID"
    WHERE c."Name" LIKE v_prefix || '%'
    ORDER BY c."Name", f."Name"
  LOOP
    v_lines := v_lines || format(
      E'INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")\n'
      || E'SELECT c."ID", %L, t.id, %s\n'
      || E'FROM "Meta"."Classes" c\n'
      || E'JOIN wf.data_type t ON t.name = %L AND t.version = %L\n'
      || E'WHERE c."Name" = %L\n'
      || E'ON CONFLICT ON CONSTRAINT "UQ_Meta_Fields_Class_Name" DO UPDATE SET "TypeID" = EXCLUDED."TypeID", "Required" = EXCLUDED."Required";\n\n',
      v_rec.field_name,
      CASE WHEN v_rec."Required" THEN 'true' ELSE 'false' END,
      v_rec.type_name,
      v_rec.version,
      v_rec.class_name
    );
  END LOOP;

  RETURN QUERY SELECT v_lines;
END;
$$;
