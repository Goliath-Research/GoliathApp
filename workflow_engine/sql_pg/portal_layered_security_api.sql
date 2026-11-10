/*
  Layered security resolution and portal.sp_* catalog helpers (no direct session).
*/

CREATE OR REPLACE FUNCTION portal.fn_meta_action_global_permission(p_action text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE lower(btrim(p_action))
    WHEN 'read' THEN 'meta.object.read'
    WHEN 'create' THEN 'meta.object.write'
    WHEN 'update' THEN 'meta.object.write'
    WHEN 'delete' THEN 'meta.object.write'
    WHEN 'author' THEN 'platform.model.author'
    ELSE NULL
  END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_role_ids_in_scope(
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
    AND (
      COALESCE(r."BypassScope", false)
      OR g."ScopeID" = p_scope_id
    );
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_class_role_effect(
  p_scope_id integer,
  p_role_id integer,
  p_class_id integer,
  p_action text
)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
  WITH RECURSIVE chain AS (
    SELECT c."ID", c."ParentID", 0 AS depth
    FROM "Meta"."Classes" c
    WHERE c."ID" = p_class_id
    UNION ALL
    SELECT p."ID", p."ParentID", chain.depth + 1
    FROM "Meta"."Classes" p
    INNER JOIN chain ON p."ID" = chain."ParentID"
  )
  SELECT a."Effect"
  FROM chain
  INNER JOIN portal."MetaClassRoleAccess" a
    ON a."ClassID" = chain."ID"
   AND a."ScopeID" = p_scope_id
   AND a."RoleID" = p_role_id
   AND a."Action" = lower(btrim(p_action))
  ORDER BY chain.depth ASC
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_effective_class_action(
  p_user_id integer,
  p_scope_id integer,
  p_class_id integer,
  p_action text
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
    SELECT r.role_id FROM portal.fn_meta_role_ids_in_scope(p_user_id, p_scope_id) r
  LOOP
    v_effect := portal.fn_meta_class_role_effect(p_scope_id, v_role_id, p_class_id, p_action);
    IF v_effect = 'deny' THEN
      CONTINUE;
    ELSIF v_effect = 'allow' THEN
      v_any_allow := true;
    ELSIF v_global IS NOT NULL
      AND portal.fn_session_meta_permission_in_active_scope(p_user_id, v_global, p_scope_id) THEN
      v_any_allow := true;
    END IF;
  END LOOP;

  RETURN v_any_allow;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_object_access_effect(
  p_scope_id integer,
  p_obj_id integer,
  p_user_id integer,
  p_action text
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
          OR a."RoleID" IN (SELECT r.role_id FROM portal.fn_meta_role_ids_in_scope(p_user_id, p_scope_id) r)
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
          OR a."RoleID" IN (SELECT r.role_id FROM portal.fn_meta_role_ids_in_scope(p_user_id, p_scope_id) r)
        )
    ) THEN 'allow'
    ELSE NULL
  END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_effective_object_action(
  p_user_id integer,
  p_scope_id integer,
  p_obj_id integer,
  p_action text
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

  v_obj_effect := portal.fn_meta_object_access_effect(p_scope_id, p_obj_id, p_user_id, p_action);
  IF v_obj_effect = 'deny' THEN
    RETURN false;
  ELSIF v_obj_effect = 'allow' THEN
    RETURN true;
  END IF;

  SELECT o."ClassID" INTO v_class_id FROM "Meta"."Objs" o WHERE o."ID" = p_obj_id;
  IF v_class_id IS NULL THEN
    RETURN false;
  END IF;

  RETURN portal.fn_meta_effective_class_action(p_user_id, p_scope_id, v_class_id, p_action);
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_assert_class_action(
  p_user_id integer,
  p_scope_id integer,
  p_class_id integer,
  p_action text
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
BEGIN
  IF NOT portal.fn_meta_effective_class_action(p_user_id, p_scope_id, p_class_id, p_action) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta class access denied');
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_meta_assert_object_action(
  p_user_id integer,
  p_scope_id integer,
  p_obj_id integer,
  p_action text
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", public, pg_temp
AS $$
BEGIN
  IF NOT portal.fn_meta_effective_object_action(p_user_id, p_scope_id, p_obj_id, p_action) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'meta object access denied');
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_upsert_class_role_access(
  p_scope_id integer,
  p_role_id integer,
  p_class_id integer,
  p_action text,
  p_effect text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_id bigint;
BEGIN
  INSERT INTO portal."MetaClassRoleAccess" (
    "ScopeID", "RoleID", "ClassID", "Action", "Effect"
  )
  VALUES (
    p_scope_id, p_role_id, p_class_id, lower(btrim(p_action)), lower(btrim(p_effect))
  )
  ON CONFLICT ON CONSTRAINT "UQ_MetaClassRoleAccess"
  DO UPDATE SET "Effect" = EXCLUDED."Effect"
  RETURNING "AccessID" INTO v_id;
  RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_list_class_role_access(
  p_scope_id integer,
  p_class_id integer
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
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
  SELECT
    a."AccessID",
    a."RoleID",
    r."Name"::text,
    a."ClassID",
    c."Name"::text,
    a."Action",
    a."Effect",
    COALESCE(anc.depth, 0)
  FROM portal."MetaClassRoleAccess" a
  INNER JOIN "RBAC"."Roles" r ON r."ID" = a."RoleID"
  INNER JOIN "Meta"."Classes" c ON c."ID" = a."ClassID"
  INNER JOIN (
    WITH RECURSIVE chain AS (
      SELECT cl."ID", cl."ParentID", 0 AS depth
      FROM "Meta"."Classes" cl
      WHERE cl."ID" = p_class_id
      UNION ALL
      SELECT p."ID", p."ParentID", chain.depth + 1
      FROM chain
      INNER JOIN "Meta"."Classes" p ON p."ID" = chain."ParentID"
    )
    SELECT chain."ID", chain.depth FROM chain
  ) anc ON anc."ID" = a."ClassID"
  WHERE a."ScopeID" = p_scope_id
  ORDER BY anc.depth, r."Name", a."Action";
$$;

CREATE OR REPLACE FUNCTION portal.sp_upsert_object_access(
  p_scope_id integer,
  p_obj_id integer,
  p_role_id integer,
  p_user_id integer,
  p_action text,
  p_effect text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_id bigint;
BEGIN
  IF p_role_id IS NOT NULL THEN
    DELETE FROM portal."MetaObjectAccess" a
    WHERE a."ScopeID" = p_scope_id
      AND a."ObjID" = p_obj_id
      AND a."RoleID" = p_role_id
      AND a."Action" = lower(btrim(p_action));
    INSERT INTO portal."MetaObjectAccess" (
      "ScopeID", "ObjID", "RoleID", "UserID", "Action", "Effect"
    )
    VALUES (
      p_scope_id, p_obj_id, p_role_id, NULL, lower(btrim(p_action)), lower(btrim(p_effect))
    )
    RETURNING "AccessID" INTO v_id;
    RETURN v_id;
  END IF;

  DELETE FROM portal."MetaObjectAccess" a
  WHERE a."ScopeID" = p_scope_id
    AND a."ObjID" = p_obj_id
    AND a."UserID" = p_user_id
    AND a."Action" = lower(btrim(p_action));
  INSERT INTO portal."MetaObjectAccess" (
    "ScopeID", "ObjID", "RoleID", "UserID", "Action", "Effect"
  )
  VALUES (
    p_scope_id, p_obj_id, NULL, p_user_id, lower(btrim(p_action)), lower(btrim(p_effect))
  )
  RETURNING "AccessID" INTO v_id;
  RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_list_object_access(
  p_scope_id integer,
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
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
  SELECT
    a."AccessID",
    a."RoleID",
    r."Name"::text,
    a."UserID",
    u."FullName"::text,
    a."Action",
    a."Effect"
  FROM portal."MetaObjectAccess" a
  LEFT JOIN "RBAC"."Roles" r ON r."ID" = a."RoleID"
  LEFT JOIN "RBAC"."Users" u ON u."ID" = a."UserID"
  WHERE a."ScopeID" = p_scope_id
    AND a."ObjID" = p_obj_id
  ORDER BY a."Action", COALESCE(r."Name", u."FullName");
$$;

SELECT portal._drop_if_proc('portal', 'sp_create_role');
CREATE OR REPLACE FUNCTION portal.sp_create_role(
  p_name text,
  p_bypass_scope boolean DEFAULT false
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_id integer;
BEGIN
  IF p_name IS NULL OR btrim(p_name) = '' THEN
    RAISE EXCEPTION 'role name required';
  END IF;
  SELECT r."ID" INTO v_id FROM "RBAC"."Roles" r WHERE r."Name" = btrim(p_name) LIMIT 1;
  IF v_id IS NOT NULL THEN
    RETURN v_id;
  END IF;
  INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
  VALUES (btrim(p_name), COALESCE(p_bypass_scope, false))
  RETURNING "ID" INTO v_id;
  RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_set_role_permission(
  p_role_id integer,
  p_permission_name text,
  p_granted boolean
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_perm_id integer;
BEGIN
  SELECT p."ID" INTO v_perm_id
  FROM "RBAC"."Permissions" p
  WHERE p."Name" = btrim(p_permission_name)
  LIMIT 1;
  IF v_perm_id IS NULL THEN
    RAISE EXCEPTION 'permission not found';
  END IF;

  IF p_granted THEN
    INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
    SELECT p_role_id, v_perm_id
    WHERE NOT EXISTS (
      SELECT 1 FROM "RBAC"."Role_Permissions" rp
      WHERE rp."RoleID" = p_role_id AND rp."PermissionID" = v_perm_id
    );
    RETURN true;
  END IF;

  DELETE FROM "RBAC"."Role_Permissions" rp
  WHERE rp."RoleID" = p_role_id AND rp."PermissionID" = v_perm_id;
  RETURN false;
END;
$$;
