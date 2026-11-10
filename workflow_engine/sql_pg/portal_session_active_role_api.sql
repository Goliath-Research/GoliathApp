/*
  Single active portal role per session (RBAC.Session_Roles).
  Callable by goliath_portal only — set via sp_session_set_active_role after grant verification.
*/

CREATE TABLE IF NOT EXISTS portal.session_active_role_audit (
  audit_id bigserial PRIMARY KEY,
  session_id integer NOT NULL,
  user_id integer NOT NULL,
  scope_id integer,
  prior_role_id integer,
  role_id integer,
  action text NOT NULL,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS "IX_portal_session_active_role_audit_session"
  ON portal.session_active_role_audit (session_id, created_at_utc DESC);

CREATE OR REPLACE FUNCTION portal.fn_session_user_selectable_role_ids(
  p_user_id integer,
  p_scope_id integer
)
RETURNS TABLE (role_id integer)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT DISTINCT g."RoleID"
  FROM "RBAC"."UserRoleGrants" g
  INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
  WHERE g."UserID" = p_user_id
    AND g."Active"
    AND g."RevokedAtUtc" IS NULL
    AND p_scope_id IS NOT NULL
    AND (
      COALESCE(r."BypassScope", false)
      OR g."ScopeID" = p_scope_id
    );
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_active_role_id(p_session_id integer)
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT sr."RoleID"
  FROM "RBAC"."Session_Roles" sr
  WHERE sr."SessionID" = p_session_id
  ORDER BY sr."RoleID"
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_role_grant_valid(
  p_user_id integer,
  p_scope_id integer,
  p_role_id integer
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM portal.fn_session_user_selectable_role_ids(p_user_id, p_scope_id) s
    WHERE s.role_id = p_role_id
  );
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_has_active_role_selected(p_session_id integer)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT portal.fn_session_active_role_id(p_session_id) IS NOT NULL;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_has_permission(
  p_session_id integer,
  p_user_id integer,
  p_active_scope_id integer,
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
    OR (
      portal.fn_session_active_role_id(p_session_id) IS NOT NULL
      AND portal.fn_session_role_grant_valid(
        p_user_id,
        p_active_scope_id,
        portal.fn_session_active_role_id(p_session_id)
      )
      AND EXISTS (
        SELECT 1
        FROM "RBAC"."Role_Permissions" rp
        INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
        WHERE rp."RoleID" = portal.fn_session_active_role_id(p_session_id)
          AND p."Name" = p_permission
      )
    );
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_audit_active_role(
  p_session_id int,
  p_user_id int,
  p_scope_id int,
  p_prior_role_id int,
  p_role_id int,
  p_action text
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  INSERT INTO portal.session_active_role_audit (
    session_id, user_id, scope_id, prior_role_id, role_id, action
  )
  VALUES (p_session_id, p_user_id, p_scope_id, p_prior_role_id, p_role_id, btrim(p_action));
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_auto_select_active_role(p_session_token text)
RETURNS TABLE (role_id integer, auto_selected boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_count int;
  v_only_role int;
  v_prior int;
BEGIN
  SELECT *
  INTO v_sess
  FROM portal.fn_session_resolve(p_session_token)
  LIMIT 1;

  IF v_sess.session_id IS NULL OR COALESCE(v_sess.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;

  IF portal.fn_session_active_role_id(v_sess.session_id) IS NOT NULL THEN
    RETURN QUERY
    SELECT portal.fn_session_active_role_id(v_sess.session_id), false;
    RETURN;
  END IF;

  IF v_sess.active_scope_id IS NULL THEN
    RETURN QUERY SELECT NULL::integer, false;
    RETURN;
  END IF;

  SELECT COUNT(*)::int, MIN(s.role_id)
  INTO v_count, v_only_role
  FROM portal.fn_session_user_selectable_role_ids(v_sess.user_id, v_sess.active_scope_id) s;

  IF v_count <> 1 OR v_only_role IS NULL THEN
    RETURN QUERY SELECT NULL::integer, false;
    RETURN;
  END IF;

  v_prior := portal.fn_session_active_role_id(v_sess.session_id);
  DELETE FROM "RBAC"."Session_Roles" WHERE "SessionID" = v_sess.session_id;
  INSERT INTO "RBAC"."Session_Roles" ("SessionID", "RoleID")
  VALUES (v_sess.session_id, v_only_role)
  ON CONFLICT DO NOTHING;

  PERFORM portal.fn_session_audit_active_role(
    v_sess.session_id, v_sess.user_id, v_sess.active_scope_id,
    v_prior, v_only_role, 'auto_select'
  );

  RETURN QUERY SELECT v_only_role, true;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_selectable_roles(p_session_token text)
RETURNS TABLE (role_id integer, role_name text)
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
    RETURN;
  END IF;

  RETURN QUERY
  SELECT s.role_id, r."Name"::text
  FROM portal.fn_session_user_selectable_role_ids(v_sess.user_id, v_sess.active_scope_id) s
  INNER JOIN "RBAC"."Roles" r ON r."ID" = s.role_id
  ORDER BY r."Name", s.role_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_get_active_role_state(p_session_token text)
RETURNS TABLE (
  active_role_id integer,
  active_role_name text,
  selectable_count integer,
  needs_selection boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_active int;
  v_count int;
BEGIN
  SELECT *
  INTO v_sess
  FROM portal.fn_session_resolve(p_session_token)
  LIMIT 1;

  IF v_sess.session_id IS NULL OR COALESCE(v_sess.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;

  v_active := portal.fn_session_active_role_id(v_sess.session_id);

  IF v_sess.active_scope_id IS NULL THEN
    RETURN QUERY SELECT v_active, NULL::text, 0, false;
    RETURN;
  END IF;

  SELECT COUNT(*)::int
  INTO v_count
  FROM portal.fn_session_user_selectable_role_ids(v_sess.user_id, v_sess.active_scope_id) s;

  RETURN QUERY
  SELECT
    v_active,
    (
      SELECT r."Name"::text
      FROM "RBAC"."Roles" r
      WHERE r."ID" = v_active
      LIMIT 1
    ),
    v_count,
    (v_active IS NULL AND v_count > 1);
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_set_active_role(
  p_session_token text,
  p_role_id integer
)
RETURNS TABLE (role_id integer, role_name text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
  v_prior int;
  v_action text;
BEGIN
  IF p_role_id IS NULL OR p_role_id <= 0 THEN
    PERFORM portal.fn_semantic_raise('GS403', 'role_id is required');
  END IF;

  SELECT *
  INTO v_sess
  FROM portal.fn_session_resolve(p_session_token)
  LIMIT 1;

  IF v_sess.session_id IS NULL OR COALESCE(v_sess.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;

  IF v_sess.active_scope_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'active scope required to select a role');
  END IF;

  IF NOT portal.fn_session_role_grant_valid(v_sess.user_id, v_sess.active_scope_id, p_role_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'role is not granted for this user in the active scope');
  END IF;

  v_prior := portal.fn_session_active_role_id(v_sess.session_id);
  v_action := CASE WHEN v_prior IS NULL THEN 'select' ELSE 'switch' END;

  DELETE FROM "RBAC"."Session_Roles" WHERE "SessionID" = v_sess.session_id;
  INSERT INTO "RBAC"."Session_Roles" ("SessionID", "RoleID")
  VALUES (v_sess.session_id, p_role_id);

  PERFORM portal.fn_session_audit_active_role(
    v_sess.session_id, v_sess.user_id, v_sess.active_scope_id,
    v_prior, p_role_id, v_action
  );

  RETURN QUERY
  SELECT p_role_id, r."Name"::text
  FROM "RBAC"."Roles" r
  WHERE r."ID" = p_role_id;
END;
$$;

DROP FUNCTION IF EXISTS portal.fn_session_resolve(text);

CREATE OR REPLACE FUNCTION portal.fn_session_resolve(p_session_token text)
RETURNS TABLE (
  session_id int,
  user_id int,
  email text,
  full_name text,
  active_scope_id int,
  active_role_id int,
  active_role_name text,
  organizations jsonb,
  expires_at_utc timestamptz,
  revoked boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", cfg, pg_temp
AS $$
DECLARE
  v_hash bytea;
  v_now timestamptz := now() AT TIME ZONE 'utc';
  v_idle int := portal.fn_session_policy_idle_seconds();
  v_abs int := portal.fn_session_policy_absolute_seconds();
  v_sid int;
  v_created timestamptz;
  v_last timestamptz;
  v_exp timestamptz;
  v_revoked timestamptz;
  v_uid int;
  v_scope int;
  v_orgs jsonb := '[]'::jsonb;
  v_role_id int;
  v_role_name text;
BEGIN
  IF NULLIF(btrim(p_session_token), '') IS NULL THEN
    RETURN;
  END IF;
  v_hash := wf.wf_sha256_text(btrim(p_session_token));

  SELECT
    st."SessionID",
    st."CreatedAtUtc",
    st."LastRefreshedAtUtc",
    st."ExpiresAtUtc",
    st."RevokedAtUtc",
    s."UserID",
    s."ActiveScopeID"
  INTO v_sid, v_created, v_last, v_exp, v_revoked, v_uid, v_scope
  FROM "RBAC"."SessionTokens" st
  INNER JOIN "RBAC"."Sessions" s ON s."ID" = st."SessionID"
  WHERE st."TokenHash" = v_hash;

  IF v_sid IS NULL OR v_revoked IS NOT NULL THEN
    RETURN;
  END IF;

  IF v_now > v_created + make_interval(secs => v_abs)
     OR v_now > v_last + make_interval(secs => v_idle)
     OR v_now > v_exp THEN
    RETURN;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM "RBAC"."Users" u WHERE u."ID" = v_uid AND u."Active" = 1
  ) THEN
    RETURN;
  END IF;

  v_role_id := portal.fn_session_active_role_id(v_sid);
  IF v_role_id IS NOT NULL THEN
    SELECT r."Name"::text INTO v_role_name
    FROM "RBAC"."Roles" r
    WHERE r."ID" = v_role_id;
  END IF;

  IF to_regclass('portal."UserOrganizations"') IS NOT NULL
     AND to_regclass('portal."Organizations"') IS NOT NULL THEN
    EXECUTE $q$
      SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'organization_id', o."ID",
        'name', o."Name"
      ) ORDER BY o."Name"), '[]'::jsonb)
      FROM portal."UserOrganizations" uo
      INNER JOIN portal."Organizations" o ON o."ID" = uo."OrganizationID"
      WHERE uo."UserID" = $1
    $q$ INTO v_orgs USING v_uid;
  END IF;

  RETURN QUERY
  SELECT
    v_sid,
    v_uid,
    u.email::text,
    u."FullName"::text,
    v_scope,
    v_role_id,
    v_role_name,
    v_orgs,
    v_exp,
    false
  FROM "RBAC"."Users" u
  WHERE u."ID" = v_uid AND u."Active" = 1;
END;
$$;

SELECT portal._drop_if_proc('portal', 'sp_session_operator_nav_tree');

CREATE OR REPLACE FUNCTION portal.sp_session_operator_nav_tree(p_session_token text)
RETURNS TABLE (
  node_id integer,
  parent_id integer,
  caption text,
  seq smallint,
  presentation_kind text,
  node_path text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", cfg, pg_temp
AS $$
DECLARE
  v_sess record;
  v_role_id int;
BEGIN
  SELECT *
  INTO v_sess
  FROM portal.fn_session_resolve(p_session_token)
  LIMIT 1;

  IF v_sess.session_id IS NULL OR COALESCE(v_sess.revoked, false) THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;

  IF v_sess.active_scope_id IS NULL THEN
    RETURN;
  END IF;

  v_role_id := portal.fn_session_active_role_id(v_sess.session_id);
  IF v_role_id IS NULL THEN
    RETURN;
  END IF;

  IF NOT portal.fn_session_role_grant_valid(v_sess.user_id, v_sess.active_scope_id, v_role_id) THEN
    RETURN;
  END IF;

  RETURN QUERY
  WITH effective_roles AS (
    SELECT v_role_id AS role_id
  ),
  user_authorized_nodes AS (
    SELECT DISTINCT rn."NodeId", n."NodePath"
    FROM portal."Role2Node" rn
    JOIN portal."NavTree" n ON n."ID" = rn."NodeId"
    JOIN effective_roles er ON er.role_id = rn."RoleId"
    WHERE rn."ScopeId" = v_sess.active_scope_id
  ),
  visible_tree AS (
    SELECT DISTINCT ON (n."ID")
      n."ID"::integer AS node_id,
      n."ParentID"::integer AS parent_id,
      n."Caption"::text AS caption,
      n."Seq"::smallint AS seq,
      n."InfoID"::integer AS info_id,
      n."SortPath"::text AS sort_path,
      n."NodePath"::text AS node_path
    FROM portal."NavTree" n
    WHERE EXISTS (
      SELECT 1
      FROM user_authorized_nodes uan
      WHERE uan."NodeId" = n."ID"
         OR (
           uan."NodePath" IS NOT NULL
           AND n."NodePath" IS NOT NULL
           AND uan."NodePath" LIKE n."NodePath" || '/%'
         )
    )
    ORDER BY n."ID", n."Seq"
  )
  SELECT
    vt.node_id,
    vt.parent_id,
    vt.caption,
    vt.seq,
    COALESCE(NULLIF(btrim(ni."FrameKey"), ''), 'view')::text AS presentation_kind,
    vt.node_path
  FROM visible_tree vt
  LEFT JOIN portal."NodeInfos" ni ON ni."Id" = vt.info_id
  ORDER BY vt.sort_path NULLS LAST, vt.seq, vt.caption;
END;
$$;

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

  IF NOT portal.fn_session_has_active_role_selected(v_sess.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
  END IF;

  IF p_node_path IS NOT NULL AND btrim(p_node_path) <> '' THEN
    IF NOT EXISTS (
      SELECT 1
      FROM portal.sp_session_operator_nav_tree(p_session_token) nt
      WHERE nt.node_path = p_node_path
    ) THEN
      PERFORM portal.fn_semantic_raise('GS403', 'operator navigation denied');
    END IF;
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

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

  IF NOT portal.fn_session_has_active_role_selected(v_sess.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
  END IF;

  IF NOT portal.fn_session_has_permission(
    v_sess.session_id, v_sess.user_id, v_sess.active_scope_id, 'platform.security.admin'
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'platform security admin permission denied');
  END IF;

  IF p_node_path IS NOT NULL AND btrim(p_node_path) <> '' THEN
    PERFORM portal.fn_session_operator_require(p_session_token, p_node_path);
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

DROP FUNCTION IF EXISTS portal.fn_session_meta_permission_in_active_scope(integer, text, integer);

CREATE OR REPLACE FUNCTION portal.fn_session_meta_permission_in_active_scope(
  p_session_id integer,
  p_user_id integer,
  p_permission text,
  p_active_scope_id integer
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT portal.fn_session_has_permission(
    p_session_id, p_user_id, p_active_scope_id, p_permission
  );
$$;

DROP FUNCTION IF EXISTS portal.fn_meta_role_ids_in_scope(integer, integer, integer);
DROP FUNCTION IF EXISTS portal.fn_meta_role_ids_in_scope(integer, integer);

CREATE OR REPLACE FUNCTION portal.fn_meta_role_ids_in_scope(
  p_user_id integer,
  p_scope_id integer,
  p_session_id integer DEFAULT NULL
)
RETURNS TABLE (role_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_role int;
BEGIN
  IF p_session_id IS NOT NULL THEN
    v_role := portal.fn_session_active_role_id(p_session_id);
    IF v_role IS NOT NULL
       AND portal.fn_session_role_grant_valid(p_user_id, p_scope_id, v_role) THEN
      RETURN QUERY SELECT v_role;
    END IF;
    RETURN;
  END IF;

  RETURN QUERY
  SELECT DISTINCT g."RoleID"
  FROM "RBAC"."UserRoleGrants" g
  INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
  WHERE g."UserID" = p_user_id
    AND g."Active"
    AND (
      COALESCE(r."BypassScope", false)
      OR g."ScopeID" = p_scope_id
    );
END;
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
BEGIN
  IF p_scope_id IS NULL THEN
    RETURN false;
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

CREATE OR REPLACE FUNCTION portal.fn_meta_effective_class_action(
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
  v_global text;
  v_any_allow boolean := false;
BEGIN
  IF p_scope_id IS NULL THEN
    RETURN false;
  END IF;

  v_global := portal.fn_meta_action_global_permission(p_action);

  FOR v_role_id IN
    SELECT r.role_id FROM portal.fn_meta_role_ids_in_scope(p_user_id, p_scope_id, p_session_id) r
  LOOP
    v_effect := portal.fn_meta_class_role_effect(p_scope_id, v_role_id, p_class_id, p_action);
    IF v_effect = 'deny' THEN
      CONTINUE;
    ELSIF v_effect = 'allow' THEN
      v_any_allow := true;
    ELSIF v_global IS NOT NULL
      AND p_session_id IS NOT NULL
      AND portal.fn_session_meta_permission_in_active_scope(
        p_session_id, p_user_id, v_global, p_scope_id
      ) THEN
      v_any_allow := true;
    ELSIF v_global IS NOT NULL AND p_session_id IS NULL THEN
      IF EXISTS (
        SELECT 1
        FROM "RBAC"."UserRoleGrants" g
        INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
        INNER JOIN "RBAC"."Role_Permissions" rp ON rp."RoleID" = g."RoleID"
        INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
        WHERE g."UserID" = p_user_id
          AND g."Active"
          AND p."Name" = v_global
          AND (
            COALESCE(r."BypassScope", false)
            OR g."ScopeID" = p_scope_id
          )
      ) THEN
        v_any_allow := true;
      END IF;
    END IF;
  END LOOP;

  RETURN v_any_allow;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_object_access_effect(
  p_scope_id integer,
  p_obj_id integer,
  p_user_id integer,
  p_action text,
  p_session_id integer DEFAULT NULL
)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT CASE
    WHEN EXISTS (
      SELECT 1
      FROM portal."MetaObjectAccess" a
      WHERE a."ScopeID" = p_scope_id
        AND a."ObjID" = p_obj_id
        AND a."Action" = lower(btrim(p_action))
        AND a."Effect" = 'deny'
        AND (
          a."UserID" = p_user_id
          OR a."RoleID" IN (
            SELECT r.role_id FROM portal.fn_meta_role_ids_in_scope(p_user_id, p_scope_id, p_session_id) r
          )
        )
    ) THEN 'deny'
    WHEN EXISTS (
      SELECT 1
      FROM portal."MetaObjectAccess" a
      WHERE a."ScopeID" = p_scope_id
        AND a."ObjID" = p_obj_id
        AND a."Action" = lower(btrim(p_action))
        AND a."Effect" = 'allow'
        AND (
          a."UserID" = p_user_id
          OR a."RoleID" IN (
            SELECT r.role_id FROM portal.fn_meta_role_ids_in_scope(p_user_id, p_scope_id, p_session_id) r
          )
        )
    ) THEN 'allow'
    ELSE NULL
  END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_meta_require_mutation_gate(
  p_user_id integer,
  p_scope_id integer,
  p_class_id integer,
  p_obj_id integer,
  p_action text,
  p_session_id integer DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
BEGIN
  IF p_session_id IS NOT NULL
     AND portal.fn_session_meta_permission_in_active_scope(
       p_session_id, p_user_id, 'meta.schema.read', p_scope_id
     ) THEN
    RETURN;
  END IF;

  IF p_obj_id IS NOT NULL
     AND portal.fn_meta_object_access_effect(
       p_scope_id, p_obj_id, p_user_id, p_action, p_session_id
     ) = 'allow' THEN
    RETURN;
  END IF;

  IF p_class_id IS NOT NULL
     AND portal.fn_meta_effective_class_action_explicit(
       p_user_id, p_scope_id, p_class_id, p_action, p_session_id
     ) THEN
    RETURN;
  END IF;

  PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied');
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_open(
  p_user_id int,
  p_active_scope_id int DEFAULT NULL,
  p_auth_provider_id int DEFAULT NULL,
  p_auth_subject_snapshot text DEFAULT NULL
)
RETURNS TABLE (session_token text, session_id int, expires_at_utc timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", cfg, pg_temp
AS $$
DECLARE
  v_session_id int;
  v_token text;
  v_hash bytea;
  v_now timestamptz := now() AT TIME ZONE 'utc';
  v_idle int := portal.fn_session_policy_idle_seconds();
  v_abs int := portal.fn_session_policy_absolute_seconds();
BEGIN
  IF p_user_id IS NULL THEN
    RAISE EXCEPTION 'user_id is required' USING ERRCODE = 'P0001';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM "RBAC"."Users" u WHERE u."ID" = p_user_id AND u."Active" = 1) THEN
    RAISE EXCEPTION 'user is inactive or unknown' USING ERRCODE = 'P0001';
  END IF;

  INSERT INTO "RBAC"."Sessions" (
    "Name", "UserID", "Created", "ActiveScopeID", "AuthProviderID",
    "AuthSubjectSnapshot", "AuthenticatedAtUtc"
  )
  VALUES (
    'portal',
    p_user_id,
    v_now,
    p_active_scope_id,
    p_auth_provider_id,
    p_auth_subject_snapshot,
    v_now
  )
  RETURNING "ID" INTO v_session_id;

  v_token := replace(
    gen_random_uuid()::text || gen_random_uuid()::text || gen_random_uuid()::text || gen_random_uuid()::text,
    '-',
    ''
  );
  v_hash := wf.wf_sha256_text(v_token);

  INSERT INTO "RBAC"."SessionTokens" (
    "SessionID", "TokenHash", "ExpiresAtUtc", "LastRefreshedAtUtc", "CreatedAtUtc"
  )
  VALUES (
    v_session_id,
    v_hash,
    v_now + make_interval(secs => v_idle),
    v_now,
    v_now
  );

  PERFORM portal.sp_session_auto_select_active_role(v_token);

  RETURN QUERY
  SELECT
    v_token,
    v_session_id,
    v_now + make_interval(secs => LEAST(v_idle, v_abs));
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_effective_object_action(
  p_user_id integer,
  p_scope_id integer,
  p_obj_id integer,
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
  v_class_id integer;
  v_obj_effect text;
BEGIN
  IF p_scope_id IS NULL THEN
    RETURN false;
  END IF;

  v_obj_effect := portal.fn_meta_object_access_effect(
    p_scope_id, p_obj_id, p_user_id, p_action, p_session_id
  );
  IF v_obj_effect = 'deny' THEN
    RETURN false;
  ELSIF v_obj_effect = 'allow' THEN
    RETURN true;
  END IF;

  SELECT o."ClassID" INTO v_class_id FROM "Meta"."Objs" o WHERE o."ID" = p_obj_id;
  IF v_class_id IS NULL THEN
    RETURN false;
  END IF;

  RETURN portal.fn_meta_effective_class_action(
    p_user_id, p_scope_id, v_class_id, p_action, p_session_id
  );
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_assert_class_action(
  p_user_id integer,
  p_scope_id integer,
  p_class_id integer,
  p_action text,
  p_session_id integer DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
BEGIN
  IF NOT portal.fn_meta_effective_class_action(
    p_user_id, p_scope_id, p_class_id, p_action, p_session_id
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta class access denied');
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_assert_object_action(
  p_user_id integer,
  p_scope_id integer,
  p_obj_id integer,
  p_action text,
  p_session_id integer DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
BEGIN
  IF NOT portal.fn_meta_effective_object_action(
    p_user_id, p_scope_id, p_obj_id, p_action, p_session_id
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta object access denied');
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_meta_require(
  p_session_token text,
  p_permission text
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

  IF NOT portal.fn_session_has_active_role_selected(v_sess.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
  END IF;

  IF NOT portal.fn_session_has_permission(
    v_sess.session_id, v_sess.user_id, v_sess.active_scope_id, p_permission
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied');
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_meta_require_instance(
  p_session_token text,
  p_permission text
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
    PERFORM portal.fn_semantic_raise('GS403', 'active scope required for meta instance access');
  END IF;

  IF NOT portal.fn_session_has_active_role_selected(v_sess.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
  END IF;

  IF NOT portal.fn_session_meta_permission_in_active_scope(
    v_sess.session_id,
    v_sess.user_id,
    p_permission,
    v_sess.active_scope_id
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied for active scope');
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
END;
$$;

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
  IF NOT portal.fn_session_has_active_role_selected(v_ctx.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
  END IF;

  IF NOT portal.fn_session_has_permission(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'meta.schema.read'
  ) THEN
    v_class_id := portal.sp_session_meta_resolve_class(p_session_token, p_class_name);
    IF NOT portal.fn_meta_effective_class_action_explicit(
      v_ctx.user_id, v_ctx.active_scope_id, v_class_id, 'create', v_ctx.session_id
    ) THEN
      PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied');
    END IF;
  ELSE
    v_class_id := portal.sp_session_meta_resolve_class(p_session_token, p_class_name);
  END IF;
  PERFORM portal.fn_meta_assert_class_action(
    v_ctx.user_id, v_ctx.active_scope_id, v_class_id, 'create', v_ctx.session_id
  );

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
  IF NOT portal.fn_session_has_active_role_selected(v_ctx.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
  END IF;

  IF NOT portal.fn_session_meta_permission_in_active_scope(
    v_ctx.session_id, v_ctx.user_id, 'meta.object.write', v_ctx.active_scope_id
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied for active scope');
  END IF;
  IF NOT portal.fn_session_has_permission(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'meta.schema.read'
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied');
  END IF;
  PERFORM portal.fn_session_meta_assert_obj_in_active_scope(p_obj_id, v_ctx.active_scope_id);
  PERFORM portal.fn_meta_assert_object_action(
    v_ctx.user_id, v_ctx.active_scope_id, p_obj_id, 'update', v_ctx.session_id
  );

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
  IF NOT portal.fn_session_has_active_role_selected(v_ctx.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
  END IF;

  PERFORM portal.fn_session_meta_assert_obj_in_active_scope(p_obj_id, v_ctx.active_scope_id);
  PERFORM portal.fn_meta_assert_object_action(
    v_ctx.user_id, v_ctx.active_scope_id, p_obj_id, 'read', v_ctx.session_id
  );

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

  IF NOT portal.fn_session_has_active_role_selected(v_sess.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
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

  IF NOT portal.fn_session_has_permission(
    v_sess.session_id, v_sess.user_id, v_sess.active_scope_id, v_req.required_permission
  ) THEN
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

  IF v_entity.meta_class_id IS NOT NULL THEN
    IF v_sess.active_scope_id IS NULL THEN
      PERFORM portal.fn_semantic_raise('GS403', 'permission denied');
    END IF;
    PERFORM portal.fn_meta_assert_class_action(
      v_sess.user_id,
      v_sess.active_scope_id,
      v_entity.meta_class_id,
      'read',
      v_sess.session_id
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
SET search_path = portal, "Meta", wf, "RBAC", public, pg_temp
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

  IF NOT portal.fn_session_has_active_role_selected(v_sess.session_id) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'portal active role required');
  END IF;

  IF NOT portal.fn_session_has_permission(
    v_sess.session_id, v_sess.user_id, v_sess.active_scope_id, 'meta.schema.read'
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied');
  END IF;

  IF NOT portal.fn_session_has_permission(
    v_sess.session_id, v_sess.user_id, v_sess.active_scope_id, 'platform.model.author'
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'platform model author permission denied');
  END IF;

  IF p_node_path IS NOT NULL AND btrim(p_node_path) <> '' THEN
    PERFORM portal.fn_session_operator_require(p_session_token, p_node_path);
  END IF;

  RETURN QUERY
  SELECT v_sess.session_id, v_sess.user_id, v_sess.active_scope_id;
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

  IF NOT portal.fn_session_has_active_role_selected(v_sess.session_id) THEN
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
  WHERE r.required_permission IS NULL
     OR portal.fn_session_has_permission(
       v_sess.session_id, v_sess.user_id, v_sess.active_scope_id, r.required_permission
     )
  ORDER BY r.namespace, r.request_code, r.version;
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
  v_session_id integer;
  v_scope_id integer;
BEGIN
  SELECT session_id, user_id, active_scope_id
  INTO v_session_id, v_user_id, v_scope_id
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
     OR portal.fn_session_has_permission(
       v_session_id, v_user_id, v_scope_id, r.required_permission
     )
  ORDER BY r.namespace, r.request_code, r.version;
END;
$$;
