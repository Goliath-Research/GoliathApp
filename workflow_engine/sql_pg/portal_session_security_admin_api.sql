/*
  Session-bound security administration and layered ACL management.
*/

CREATE OR REPLACE FUNCTION portal.fn_session_security_admin_require(
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
SET search_path = portal, "RBAC", public, pg_temp
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
    PERFORM portal.fn_semantic_raise('GS403', 'active scope required for security admin');
  END IF;

  IF NOT portal.fn_semantic_session_has_permission(v_sess.user_id, 'platform.security.admin') THEN
    PERFORM portal.fn_semantic_raise('GS403', 'platform security admin permission denied');
  END IF;

  IF p_node_path IS NOT NULL AND btrim(p_node_path) <> '' THEN
    PERFORM portal.fn_session_operator_require(p_session_token, p_node_path);
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_security_admin_audit(
  p_session_id int,
  p_actor_user_id int,
  p_scope_id int,
  p_action text,
  p_payload jsonb
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  INSERT INTO portal.security_admin_audit (session_id, actor_user_id, scope_id, action_code, payload)
  VALUES (p_session_id, p_actor_user_id, p_scope_id, p_action, COALESCE(p_payload, '{}'::jsonb));
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_upsert_user(
  p_session_token text,
  p_email text,
  p_full_name text,
  p_active int DEFAULT 1
)
RETURNS TABLE (user_id int)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_uid int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  SELECT portal.sp_upsert_user(p_email, p_full_name, p_active) INTO v_uid;
  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'user.upsert',
    jsonb_build_object('email', p_email, 'user_id', v_uid)
  );
  RETURN QUERY SELECT v_uid;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_grant_user_role_admin(
  p_session_token text,
  p_target_user_id integer,
  p_role_id integer
)
RETURNS TABLE (inserted boolean, grant_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  RETURN QUERY
  SELECT g.inserted, g.grant_id
  FROM portal.sp_grant_user_role(p_target_user_id, p_role_id, 'SCOPED', v_ctx.active_scope_id, NULL) g;
  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'user.grant_role',
    jsonb_build_object('target_user_id', p_target_user_id, 'role_id', p_role_id)
  );
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_revoke_user_role_scoped(
  p_session_token text,
  p_target_user_id integer,
  p_role_id integer
)
RETURNS TABLE (revoked boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_ok boolean;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  SELECT (g.rows_updated > 0) INTO v_ok
  FROM portal.sp_revoke_user_role(p_target_user_id, p_role_id, 'SCOPED', v_ctx.active_scope_id) g;
  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'user.revoke_role',
    jsonb_build_object('target_user_id', p_target_user_id, 'role_id', p_role_id)
  );
  RETURN QUERY SELECT COALESCE(v_ok, false);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_create_role(
  p_session_token text,
  p_name text
)
RETURNS TABLE (role_id int)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_rid int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/roles') LIMIT 1;
  v_rid := portal.sp_create_role(p_name, false);
  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'role.create',
    jsonb_build_object('name', p_name, 'role_id', v_rid)
  );
  RETURN QUERY SELECT v_rid;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_set_role_permission(
  p_session_token text,
  p_role_id integer,
  p_permission_name text,
  p_granted boolean
)
RETURNS TABLE (granted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_ok boolean;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/roles') LIMIT 1;
  v_ok := portal.sp_set_role_permission(p_role_id, p_permission_name, p_granted);
  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'role.set_permission',
    jsonb_build_object('role_id', p_role_id, 'permission', p_permission_name, 'granted', p_granted)
  );
  RETURN QUERY SELECT v_ok;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_create_invitation_scoped(
  p_session_token text,
  p_email text,
  p_default_role_id integer
)
RETURNS TABLE (invitation_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", "Onboarding", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_id bigint;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  SELECT i.invitation_id INTO v_id
  FROM portal.sp_create_invitation(
    v_ctx.active_scope_id,
    p_email,
    NULL,
    (now() AT TIME ZONE 'utc') + interval '14 days',
    NULL,
    p_default_role_id,
    'SCOPED',
    NULL
  ) i;
  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'user.invite',
    jsonb_build_object('email', p_email, 'invitation_id', v_id)
  );
  RETURN QUERY SELECT v_id;
END;
$$;

DROP FUNCTION IF EXISTS portal.sp_session_list_user_role_grants_scoped(text, integer);

CREATE OR REPLACE FUNCTION portal.sp_session_list_user_role_grants_scoped(
  p_session_token text,
  p_target_user_id integer
)
RETURNS TABLE (
  grant_id bigint,
  role_id int,
  role_name text,
  grant_type text,
  scope_id int,
  active boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  RETURN QUERY
  SELECT g.grant_id, g.role_id, g.role_name, g.grant_type, g.scope_id, g.active
  FROM portal.sp_list_user_role_grants(p_target_user_id) g
  WHERE g.scope_id = v_ctx.active_scope_id OR g.scope_id IS NULL;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_upsert_class_role_access(
  p_session_token text,
  p_class_name text,
  p_role_id integer,
  p_action text,
  p_effect text
)
RETURNS TABLE (access_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
  v_id bigint;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/meta/classes') LIMIT 1;
  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = btrim(p_class_name);
  IF v_class_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta class not found');
  END IF;
  v_id := portal.sp_upsert_class_role_access(v_ctx.active_scope_id, p_role_id, v_class_id, p_action, p_effect);
  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'class.access.upsert',
    jsonb_build_object('class_name', p_class_name, 'role_id', p_role_id, 'action', p_action, 'effect', p_effect)
  );
  RETURN QUERY SELECT v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_class_role_access(
  p_session_token text,
  p_class_name text
)
RETURNS TABLE (
  access_id bigint,
  role_id integer,
  role_name text,
  class_id integer,
  class_name text,
  action text,
  effect text,
  declared_depth integer
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
BEGIN
  PERFORM portal.fn_session_meta_require(p_session_token, 'meta.schema.read');
  SELECT * INTO v_ctx FROM portal.fn_session_resolve(p_session_token) LIMIT 1;
  IF v_ctx.active_scope_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'active scope required');
  END IF;
  SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = btrim(p_class_name);
  IF v_class_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'meta class not found');
  END IF;
  RETURN QUERY
  SELECT * FROM portal.sp_list_class_role_access(v_ctx.active_scope_id, v_class_id);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_upsert_object_access(
  p_session_token text,
  p_obj_id integer,
  p_role_id integer,
  p_user_id integer,
  p_action text,
  p_effect text
)
RETURNS TABLE (access_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_id bigint;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/meta/objects') LIMIT 1;
  PERFORM portal.fn_session_meta_assert_obj_in_active_scope(p_obj_id, v_ctx.active_scope_id);
  v_id := portal.sp_upsert_object_access(
    v_ctx.active_scope_id, p_obj_id, p_role_id, p_user_id, p_action, p_effect
  );
  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'object.access.upsert',
    jsonb_build_object('obj_id', p_obj_id, 'role_id', p_role_id, 'user_id', p_user_id, 'action', p_action)
  );
  RETURN QUERY SELECT v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_object_access(
  p_session_token text,
  p_obj_id integer
)
RETURNS TABLE (
  access_id bigint,
  role_id integer,
  role_name text,
  user_id integer,
  user_name text,
  action text,
  effect text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_meta_require_instance(p_session_token, 'meta.object.read') LIMIT 1;
  PERFORM portal.fn_session_meta_assert_obj_in_active_scope(p_obj_id, v_ctx.active_scope_id);
  RETURN QUERY SELECT * FROM portal.sp_list_object_access(v_ctx.active_scope_id, p_obj_id);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_effective_permissions_check(
  p_session_token text,
  p_target_user_id integer,
  p_class_name text DEFAULT NULL,
  p_obj_id integer DEFAULT NULL,
  p_action text DEFAULT 'read'
)
RETURNS TABLE (
  allowed boolean,
  resolution_summary text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_class_id int;
  v_allowed boolean;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;

  IF p_obj_id IS NOT NULL THEN
    v_allowed := portal.fn_meta_effective_object_action(
      p_target_user_id, v_ctx.active_scope_id, p_obj_id, p_action
    );
    RETURN QUERY SELECT v_allowed, format('object %s action %s', p_obj_id, p_action);
    RETURN;
  END IF;

  IF p_class_name IS NOT NULL AND btrim(p_class_name) <> '' THEN
    SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = btrim(p_class_name);
    IF v_class_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS404', 'meta class not found');
    END IF;
    v_allowed := portal.fn_meta_effective_class_action(
      p_target_user_id, v_ctx.active_scope_id, v_class_id, p_action
    );
    RETURN QUERY SELECT v_allowed, format('class %s action %s', p_class_name, p_action);
    RETURN;
  END IF;

  PERFORM portal.fn_semantic_raise('GS400', 'class_name or obj_id required');
END;
$$;
