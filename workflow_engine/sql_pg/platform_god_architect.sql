-- God Architect: sole platform-level model authority for GoliathApp-owned platform catalog.
-- Child apps model their own product classes; the platform namespace stays god_architect-only.

CREATE TABLE IF NOT EXISTS portal.god_architect_audit (
  audit_id bigserial PRIMARY KEY,
  session_id integer NOT NULL,
  actor_user_id integer NOT NULL,
  action_code text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
SELECT 'god_architect', true
WHERE NOT EXISTS (SELECT 1 FROM "RBAC"."Roles" r WHERE r."Name" = 'god_architect');

CREATE OR REPLACE FUNCTION portal.fn_god_architect_role_id()
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT r."ID" FROM "RBAC"."Roles" r WHERE r."Name" = 'god_architect' LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_is_god_architect_role(p_role_id integer)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT p_role_id IS NOT NULL
    AND p_role_id = portal.fn_god_architect_role_id();
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_platform_security_data_class(p_class_name text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT COALESCE(p_class_name, '') IN (
    'platform/User',
    'platform/RoleGrant',
    'platform/Invitation',
    'platform/ExternalIdentity',
    'platform/Organization'
  );
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_platform_god_architect_class(p_class_name text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT COALESCE(p_class_name, '') LIKE 'platform/%'
    AND NOT portal.fn_meta_platform_security_data_class(p_class_name);
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_platform_god_architect_class_id(p_class_id integer)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
  SELECT portal.fn_meta_platform_god_architect_class(c."Name")
  FROM "Meta"."Classes" c
  WHERE c."ID" = p_class_id;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_assert_god_architect(p_session_token text)
RETURNS TABLE (session_id integer, user_id integer, active_scope_id integer, role_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_role int;
BEGIN
  SELECT * INTO v_sess FROM portal.fn_session_resolve(p_session_token) LIMIT 1;
  IF v_sess.session_id IS NULL OR COALESCE(v_sess.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;
  IF NOT portal.fn_session_has_active_role_selected(v_sess.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
  END IF;

  v_role := portal.fn_session_active_role_id(v_sess.session_id);
  IF NOT portal.fn_session_is_god_architect_role(v_role) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'God Architect role required');
  END IF;

  IF NOT portal.fn_session_has_permission(
    v_sess.session_id, v_sess.user_id, v_sess.active_scope_id, 'platform.model.architect'
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'platform.model.architect permission denied');
  END IF;

  RETURN QUERY SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id, v_role;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_god_architect_audit(
  p_session_id int,
  p_user_id int,
  p_action text,
  p_payload jsonb DEFAULT '{}'::jsonb
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  INSERT INTO portal.god_architect_audit (session_id, actor_user_id, action_code, payload)
  VALUES (p_session_id, p_user_id, btrim(p_action), COALESCE(p_payload, '{}'::jsonb));
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_model_author_require_god(
  p_session_token text,
  p_node_path text DEFAULT NULL
)
RETURNS TABLE (session_id integer, user_id integer, active_scope_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ga record;
BEGIN
  SELECT * INTO v_ga FROM portal.fn_session_assert_god_architect(p_session_token) LIMIT 1;

  IF p_node_path IS NOT NULL AND btrim(p_node_path) <> '' THEN
    PERFORM portal.fn_session_operator_require(p_session_token, p_node_path);
  END IF;

  IF NOT portal.fn_session_has_permission(
    v_ga.session_id, v_ga.user_id, v_ga.active_scope_id, 'meta.schema.read'
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta.schema.read required');
  END IF;

  RETURN QUERY SELECT v_ga.session_id, v_ga.user_id, v_ga.active_scope_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_model_author_require_platform_catalog(
  p_session_token text,
  p_node_path text DEFAULT NULL
)
RETURNS TABLE (session_id integer, user_id integer, active_scope_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
BEGIN
  RETURN QUERY
  SELECT * FROM portal.fn_session_model_author_require_god(p_session_token, p_node_path);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_security_meta_ensure_god_architect_catalog()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_class_role int;
  v_class_perm int;
  v_role_rbac int;
  v_perm_id int;
  v_doc jsonb;
  v_obj int;
BEGIN
  v_role_rbac := portal.fn_god_architect_role_id();
  IF v_role_rbac IS NULL THEN
    RETURN;
  END IF;

  SELECT c."ID" INTO v_class_role FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Role';
  SELECT c."ID" INTO v_class_perm FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Permission';
  IF v_class_role IS NULL OR v_class_perm IS NULL THEN
    RETURN;
  END IF;

  SELECT m.meta_obj_id INTO v_obj
  FROM portal.security_meta_legacy_map m
  WHERE m.legacy_kind = 'role' AND m.legacy_id = v_role_rbac;
  v_doc := jsonb_build_object(
    'Label', 'God Architect',
    'RoleName', 'god_architect',
    'BypassScope', true,
    'LegacyRoleId', v_role_rbac
  );
  IF v_obj IS NULL THEN
    v_obj := "Meta".sp_obj_insert(v_class_role, v_doc);
    PERFORM portal.sp_security_meta_upsert_map('role', v_role_rbac, v_obj);
  ELSE
    UPDATE "Meta"."ObjValues" ov
    SET "Data" = v_doc
  WHERE ov."ObjID" = v_obj AND ov."ClassID" = v_class_role;
  END IF;

  SELECT p."ID" INTO v_perm_id FROM "RBAC"."Permissions" p WHERE p."Name" = 'platform.model.architect';
  IF v_perm_id IS NOT NULL THEN
    SELECT m.meta_obj_id INTO v_obj
    FROM portal.security_meta_legacy_map m
    WHERE m.legacy_kind = 'permission' AND m.legacy_id = v_perm_id;
    v_doc := jsonb_build_object(
      'Label', 'platform.model.architect',
      'PermissionName', 'platform.model.architect',
      'LegacyPermissionId', v_perm_id
    );
    IF v_obj IS NULL THEN
      v_obj := "Meta".sp_obj_insert(v_class_perm, v_doc);
      PERFORM portal.sp_security_meta_upsert_map('permission', v_perm_id, v_obj);
    END IF;

    INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
    SELECT v_role_rbac, v_perm_id
    WHERE NOT EXISTS (
      SELECT 1 FROM "RBAC"."Role_Permissions" rp
      WHERE rp."RoleID" = v_role_rbac AND rp."PermissionID" = v_perm_id
    );
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_security_meta_grant_god_architect_to_user(p_user_id integer)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_role_id int;
  v_grant_id bigint;
BEGIN
  IF p_user_id IS NULL OR p_user_id <= 0 THEN
    RAISE EXCEPTION 'user_id is required';
  END IF;

  v_role_id := portal.fn_god_architect_role_id();
  IF v_role_id IS NULL THEN
    RAISE EXCEPTION 'god_architect role is missing';
  END IF;

  SELECT g."ID"
  INTO v_grant_id
  FROM "RBAC"."UserRoleGrants" g
  WHERE g."UserID" = p_user_id
    AND g."RoleID" = v_role_id
    AND g."GrantType" = 'GLOBAL'
    AND g."Active"
    AND g."RevokedAtUtc" IS NULL
  LIMIT 1;

  IF v_grant_id IS NULL THEN
    INSERT INTO "RBAC"."UserRoleGrants" (
      "UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc"
    )
    VALUES (
      p_user_id, v_role_id, 'GLOBAL', NULL, true, now() AT TIME ZONE 'utc'
    )
    RETURNING "ID" INTO v_grant_id;
  END IF;

  IF to_regprocedure('portal.sp_security_meta_upsert_role_grant_from_rbac(bigint)') IS NOT NULL THEN
    PERFORM portal.sp_security_meta_upsert_role_grant_from_rbac(v_grant_id);
  END IF;

  RETURN v_grant_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_security_user_grant_role_ids(
  p_user_id integer,
  p_scope_id integer
)
RETURNS TABLE (role_id integer)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  SELECT DISTINCT g.role_id
  FROM portal.mv_security_effective_grants g
  WHERE g.user_id = p_user_id
    AND (
      g.bypass_scope
      OR g.scope_id = p_scope_id
    );
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_effective_class_action_explicit(
  p_user_id integer,
  p_scope_id integer,
  p_class_id integer,
  p_action text,
  p_session_id integer DEFAULT NULL
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
DECLARE
  v_role_id integer;
  v_effect text;
  v_class_name text;
  v_active_role int;
BEGIN
  IF p_scope_id IS NULL THEN
    RETURN false;
  END IF;

  SELECT c."Name" INTO v_class_name FROM "Meta"."Classes" c WHERE c."ID" = p_class_id;

  IF portal.fn_meta_platform_god_architect_class(v_class_name)
     AND lower(btrim(p_action)) IN ('create', 'update', 'delete') THEN
  v_active_role := CASE WHEN p_session_id IS NULL THEN NULL ELSE portal.fn_session_active_role_id(p_session_id) END;
    RETURN portal.fn_session_is_god_architect_role(v_active_role);
  END IF;

  FOR v_role_id IN
    SELECT r.role_id FROM portal.fn_meta_role_ids_in_scope(p_user_id, p_scope_id, p_session_id) r
  LOOP
    v_effect := portal.fn_meta_class_role_effect(p_scope_id, v_role_id, p_class_id, p_action);
    IF v_effect = 'allow' THEN
      RETURN true;
    END IF;
  END LOOP;

  RETURN false;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_security_meta_verify_production()
RETURNS TABLE (
  check_name text,
  ok boolean,
  detail text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_admin_role int;
  v_god_role int;
BEGIN
  SELECT r."ID" INTO v_admin_role FROM "RBAC"."Roles" r WHERE r."Name" = 'organization_admin' LIMIT 1;
  v_god_role := portal.fn_god_architect_role_id();

  RETURN QUERY
  SELECT
    'david_org_admin_scope_1'::text,
    EXISTS (
      SELECT 1 FROM portal.mv_security_effective_grants g
      WHERE g.user_id = 1 AND g.scope_id = 1 AND g.role_id = v_admin_role
    ),
    format('user_id=1 scope_id=1 role organization_admin (id %s)', v_admin_role)::text;

  RETURN QUERY
  SELECT
    'inty_org_admin_scope_1'::text,
    EXISTS (
      SELECT 1 FROM portal.mv_security_effective_grants g
      WHERE g.user_id = 2 AND g.scope_id = 1 AND g.role_id = v_admin_role
    ),
    format('user_id=2 scope_id=1 role organization_admin (id %s)', v_admin_role)::text;

  RETURN QUERY
  SELECT
    'david_god_architect_global'::text,
    EXISTS (
      SELECT 1 FROM portal.mv_security_effective_grants g
      WHERE g.user_id = 1 AND g.role_id = v_god_role AND COALESCE(g.bypass_scope, false)
    ),
    format('user_id=1 god_architect global (role id %s)', v_god_role)::text;

  RETURN QUERY
  SELECT
    'god_architect_role_seeded'::text,
    v_god_role IS NOT NULL,
    'RBAC.Roles god_architect exists'::text;

  RETURN QUERY
  SELECT
    'david_entra_identity_meta'::text,
    EXISTS (
      SELECT 1
      FROM "Meta"."ObjValues" ov
      WHERE ov."ClassID" = (SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/ExternalIdentity' LIMIT 1)
        AND (ov."Data"->>'LegacyUserId')::int = 1
        AND (ov."Data"->>'ProviderId')::int = 1
        AND COALESCE((ov."Data"->>'Active')::boolean, false)
    ),
    'External identity for user 1 provider 1 present in Meta'::text;

  RETURN QUERY
  SELECT
    'meta_user_ids_preserved'::text,
    portal.fn_security_meta_user_legacy_map_ok(1)
      AND portal.fn_security_meta_user_legacy_map_ok(2),
    'Users 1 and 2 map via security_meta_legacy_map to platform/User with LegacyUserId'::text;
END;
$$;

DO $god_perm$
DECLARE
  v_class_id int;
  v_obj_id int;
  v_op_id int;
  v_god_role int;
BEGIN
  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = 'portal/NavNode' LIMIT 1;
  IF v_class_id IS NULL THEN
    RETURN;
  END IF;
  SELECT o."ID" INTO v_obj_id FROM "Meta"."Objs" o ORDER BY o."ID" LIMIT 1;
  IF v_obj_id IS NULL THEN
    INSERT INTO "Meta"."Objs" ("ClassID") VALUES (v_class_id) RETURNING "ID" INTO v_obj_id;
  END IF;
  SELECT op."ID" INTO v_op_id FROM "Meta"."Operations" op WHERE op."Name" = 'meta.permission_anchor' LIMIT 1;
  IF v_op_id IS NULL THEN
    INSERT INTO "Meta"."Operations" ("Name", "ClassID")
    VALUES ('meta.permission_anchor', v_class_id) RETURNING "ID" INTO v_op_id;
  END IF;

  INSERT INTO "RBAC"."Permissions" ("Name", "ObjID", "OperationID")
  SELECT 'platform.model.architect', v_obj_id, v_op_id
  WHERE NOT EXISTS (SELECT 1 FROM "RBAC"."Permissions" p WHERE p."Name" = 'platform.model.architect');

  v_god_role := portal.fn_god_architect_role_id();
  IF v_god_role IS NOT NULL THEN
    INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
    SELECT v_god_role, p."ID"
    FROM "RBAC"."Permissions" p
    WHERE p."Name" = 'platform.model.architect'
      AND NOT EXISTS (
        SELECT 1 FROM "RBAC"."Role_Permissions" rp
        WHERE rp."RoleID" = v_god_role AND rp."PermissionID" = p."ID"
      );
  END IF;
END
$god_perm$;

SELECT portal.sp_security_meta_ensure_god_architect_catalog();
DO $grant_god$
BEGIN
  IF EXISTS (
    SELECT 1 FROM "RBAC"."Users" u WHERE u."ID" = 1 AND u."Active" = 1
  ) THEN
    PERFORM portal.sp_security_meta_grant_god_architect_to_user(1);
  END IF;
END
$grant_god$;
SELECT portal.sp_security_meta_refresh_cache();

DO $god_acl$
DECLARE
  v_scope int;
  v_god_role int;
  v_admin_role int;
  v_class record;
BEGIN
  SELECT MIN(s."ScopeID") INTO v_scope FROM "RBAC"."Scopes" s WHERE s."Active" = true;
  v_god_role := portal.fn_god_architect_role_id();
  SELECT r."ID" INTO v_admin_role FROM "RBAC"."Roles" r WHERE r."Name" = 'organization_admin' LIMIT 1;

  IF v_scope IS NULL OR v_god_role IS NULL THEN
    RETURN;
  END IF;

  FOR v_class IN
    SELECT c."ID" AS class_id, c."Name" AS class_name
    FROM "Meta"."Classes" c
    WHERE c."Name" LIKE 'platform/%'
       OR c."Name" = 'portal/NavNode'
  LOOP
    IF portal.fn_meta_platform_security_data_class(v_class.class_name) THEN
      CONTINUE;
    END IF;

    INSERT INTO portal."MetaClassRoleAccess" ("ScopeID", "RoleID", "ClassID", "Action", "Effect")
    SELECT v_scope, v_god_role, v_class.class_id, act, 'allow'
    FROM unnest(ARRAY['create', 'update', 'delete', 'read']::text[]) AS act
    ON CONFLICT ON CONSTRAINT "UQ_MetaClassRoleAccess"
    DO UPDATE SET "Effect" = 'allow';

    IF v_admin_role IS NOT NULL THEN
      INSERT INTO portal."MetaClassRoleAccess" ("ScopeID", "RoleID", "ClassID", "Action", "Effect")
      SELECT v_scope, v_admin_role, v_class.class_id, act, 'deny'
      FROM unnest(ARRAY['create', 'update', 'delete']::text[]) AS act
      ON CONFLICT ON CONSTRAINT "UQ_MetaClassRoleAccess"
      DO UPDATE SET "Effect" = 'deny';
    END IF;
  END LOOP;
END
$god_acl$;

CREATE OR REPLACE FUNCTION portal.sp_session_meta_class_create(
  p_session_token text,
  p_class_name text,
  p_parent_class_name text DEFAULT NULL
)
RETURNS TABLE (class_id integer, class_name text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_parent_id int;
  v_new_id int;
  v_name text := btrim(p_class_name);
BEGIN
  IF v_name LIKE 'platform/%' THEN
    SELECT * INTO v_ctx FROM portal.fn_session_model_author_require_god(p_session_token, '/app/meta/classes') LIMIT 1;
  ELSE
    SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/meta/classes') LIMIT 1;
  END IF;

  IF v_name IS NULL OR v_name = '' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'class_name required');
  END IF;
  IF EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = v_name) THEN
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
  VALUES (v_name, v_parent_id)
  RETURNING "ID" INTO v_new_id;

  PERFORM "Meta".sp_refresh_class_hierarchy(v_new_id);
  PERFORM "Meta".sp_meta_publish_class_type(v_new_id, false);
  PERFORM "Meta".sp_class_regenerate_views(v_new_id);

  IF v_name LIKE 'platform/%' THEN
    PERFORM portal.fn_session_god_architect_audit(
      v_ctx.session_id, v_ctx.user_id, 'platform.class.create',
      jsonb_build_object('class_name', v_name, 'parent', p_parent_class_name)
    );
  ELSE
    PERFORM portal.fn_session_model_author_audit(
      v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
      'meta.class.create',
      jsonb_build_object('class_name', v_name, 'parent', p_parent_class_name)
    );
  END IF;

  RETURN QUERY SELECT v_new_id, v_name::text;
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
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
  v_type_id bigint;
  v_field_id int;
  v_class text := btrim(p_class_name);
BEGIN
  IF portal.fn_meta_platform_god_architect_class(v_class) OR v_class LIKE 'platform/%' THEN
    SELECT * INTO v_ctx FROM portal.fn_session_model_author_require_god(p_session_token, '/app/meta/classes') LIMIT 1;
  ELSE
    SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/meta/classes') LIMIT 1;
  END IF;

  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = v_class;
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

  IF v_class LIKE 'platform/%' THEN
    PERFORM portal.fn_session_god_architect_audit(
      v_ctx.session_id, v_ctx.user_id, 'platform.field.upsert',
      jsonb_build_object('class_name', v_class, 'field_name', p_field_name)
    );
  ELSE
    PERFORM portal.fn_session_model_author_audit(
      v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
      'meta.field.upsert',
      jsonb_build_object('class_name', v_class, 'field_name', p_field_name)
    );
  END IF;

  RETURN QUERY SELECT v_field_id;
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
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_node int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require_god(p_session_token, '/app/admin/navigation') LIMIT 1;

  SELECT portal.sp_nav_register_node(
    p_parent_nav_id, btrim(p_caption), p_seq, NULL, p_node_path, NULL
  ) INTO v_node;

  PERFORM portal.fn_session_god_architect_audit(
    v_ctx.session_id, v_ctx.user_id, 'platform.nav.register',
    jsonb_build_object('caption', p_caption, 'node_path', p_node_path, 'node_id', v_node)
  );

  RETURN QUERY SELECT v_node;
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
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_meta_class_id int;
  v_entity_id int;
  v_ns text := lower(btrim(p_namespace));
BEGIN
  IF v_ns IN ('platform', 'portal', 'core') THEN
    SELECT * INTO v_ctx FROM portal.fn_session_model_author_require_god(p_session_token, '/app/semantic') LIMIT 1;
  ELSE
    SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/semantic') LIMIT 1;
  END IF;

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

  IF v_ns IN ('platform', 'portal', 'core') THEN
    PERFORM portal.fn_session_god_architect_audit(
      v_ctx.session_id, v_ctx.user_id, 'platform.semantic.entity.register',
      jsonb_build_object('namespace', p_namespace, 'code', p_code)
    );
  ELSE
    PERFORM portal.fn_session_model_author_audit(
      v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
      'semantic.entity.register',
      jsonb_build_object('namespace', p_namespace, 'code', p_code, 'meta_class_name', p_meta_class_name)
    );
  END IF;

  RETURN QUERY SELECT v_entity_id;
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
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_ga record;
  v_god int;
  v_inserted boolean;
  v_grant_id bigint;
BEGIN
  v_god := portal.fn_god_architect_role_id();
  IF p_role_id = v_god THEN
    SELECT * INTO v_ga FROM portal.fn_session_assert_god_architect(p_session_token) LIMIT 1;
    SELECT g.inserted, g.grant_id
    INTO v_inserted, v_grant_id
    FROM portal.sp_grant_user_role(p_target_user_id, p_role_id, 'GLOBAL', NULL, NULL) g;
    PERFORM portal.fn_session_god_architect_audit(
      v_ga.session_id, v_ga.user_id, 'platform.grant.god_architect',
      jsonb_build_object('target_user_id', p_target_user_id, 'grant_id', v_grant_id)
    );
    RETURN QUERY SELECT v_inserted, v_grant_id;
    RETURN;
  END IF;

  SELECT * INTO v_ctx FROM portal.fn_session_model_author_require(p_session_token, '/app/admin/navigation') LIMIT 1;

  RETURN QUERY
  SELECT g.inserted, g.grant_id
  FROM portal.sp_grant_user_role(p_target_user_id, p_role_id, 'SCOPED', v_ctx.active_scope_id, NULL) g;

  PERFORM portal.fn_session_model_author_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
    'rbac.grant_user_role',
    jsonb_build_object('target_user_id', p_target_user_id, 'role_id', p_role_id)
  );
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_revoke_user_role_grant(
  p_session_token text,
  p_grant_id bigint
)
RETURNS TABLE (revoked boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_ga record;
  v_grant_obj int;
  v_grant_class int;
  v_user_id int;
  v_role_id int;
  v_scope_id int;
  v_grant_type text;
  v_role_name text;
  v_org_admin_id int;
  v_god_role int;
  v_peer_admin_count int;
  v_peer_god_count int;
  v_now text;
BEGIN
  v_god_role := portal.fn_god_architect_role_id();
  SELECT c."ID" INTO v_grant_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/RoleGrant';

  SELECT ov."ObjID",
         (ov."Data"->>'LegacyUserId')::int,
         (ov."Data"->>'LegacyRoleId')::int,
         (ov."Data"->>'LegacyScopeId')::int,
         COALESCE(ov."Data"->>'GrantType', 'SCOPED')
  INTO v_grant_obj, v_user_id, v_role_id, v_scope_id, v_grant_type
  FROM "Meta"."ObjValues" ov
  WHERE ov."ClassID" = v_grant_class
    AND (ov."Data"->>'LegacyGrantId')::bigint = p_grant_id
    AND COALESCE((ov."Data"->>'Active')::boolean, false)
  LIMIT 1;

  IF v_grant_obj IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'role grant not found');
  END IF;

  IF v_role_id = v_god_role THEN
    SELECT * INTO v_ga FROM portal.fn_session_assert_god_architect(p_session_token) LIMIT 1;
    SELECT COUNT(*)::int INTO v_peer_god_count
    FROM portal.mv_security_effective_grants g
    WHERE g.role_id = v_god_role AND COALESCE(g.bypass_scope, false);
    IF v_peer_god_count <= 1 THEN
      PERFORM portal.fn_semantic_raise('GS403', 'cannot revoke the last God Architect grant');
    END IF;
    v_now := to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
    UPDATE "Meta"."ObjValues" ov
    SET "Data" = ov."Data"
      || jsonb_build_object('Active', false, 'RevokedAtUtc', v_now)
    WHERE ov."ObjID" = v_grant_obj AND ov."ClassID" = v_grant_class;
    PERFORM portal.fn_session_god_architect_audit(
      v_ga.session_id, v_ga.user_id, 'platform.revoke.god_architect',
      jsonb_build_object('grant_id', p_grant_id, 'target_user_id', v_user_id)
    );
    RETURN QUERY SELECT true;
    RETURN;
  END IF;

  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;

  IF v_grant_type <> 'GLOBAL' AND v_scope_id IS DISTINCT FROM v_ctx.active_scope_id THEN
    PERFORM portal.fn_semantic_raise('GS403', 'role grant is outside the active scope');
  END IF;

  SELECT (rov."Data"->>'LegacyRoleId')::int INTO v_org_admin_id
  FROM "Meta"."ObjValues" rov
  WHERE rov."ClassID" = (SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Role')
    AND rov."Data"->>'RoleName' = 'organization_admin'
  LIMIT 1;

  IF v_org_admin_id IS NOT NULL AND v_role_id = v_org_admin_id AND v_user_id = v_ctx.user_id THEN
    SELECT COUNT(*)::int INTO v_peer_admin_count
    FROM portal.mv_security_effective_grants g
    WHERE g.role_id = v_org_admin_id AND g.scope_id = v_ctx.active_scope_id;
    IF v_peer_admin_count <= 1 THEN
      PERFORM portal.fn_semantic_raise('GS403', 'cannot revoke your last organization_admin grant in this scope');
    END IF;
  END IF;

  SELECT rov."Data"->>'RoleName' INTO v_role_name
  FROM "Meta"."ObjValues" rov
  WHERE rov."ClassID" = (SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Role')
    AND (rov."Data"->>'LegacyRoleId')::int = v_role_id
  LIMIT 1;

  v_now := to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
  UPDATE "Meta"."ObjValues" ov
  SET "Data" = ov."Data"
    || jsonb_build_object('Active', false, 'RevokedAtUtc', v_now)
  WHERE ov."ObjID" = v_grant_obj AND ov."ClassID" = v_grant_class;

  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id,
    'user.revoke_role_grant',
    jsonb_build_object(
      'grant_id', p_grant_id,
      'target_user_id', v_user_id,
      'role_id', v_role_id,
      'role_name', v_role_name
    )
  );

  RETURN QUERY SELECT true;
END;
$$;
