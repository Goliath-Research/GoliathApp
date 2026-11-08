/*
  Session-bound operator navigation (portal.sp_session_* + RBAC NavTree).
  Callable by goliath_portal only — tokens stay server-side in the platform host BFF.

  Scope invariant (P1): Role2Node rows match only when the session carries a non-null
  ActiveScopeID equal to Role2Node.ScopeId. Sessions without active scope see no operator
  nav (fail closed — no cross-tenant flattening when scope is missing).

  Role resolution merges legacy portal.UserRoles, scoped UserRoleGrants for the session's
  active scope (or BypassScope roles), and RBAC.usp_session_get_effective_roles_v2.
*/

CREATE OR REPLACE FUNCTION portal.sp_session_operator_nav_tree(p_session_token text)
RETURNS TABLE (
  node_id integer,
  parent_id integer,
  caption text,
  seq smallint,
  presentation_kind text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", cfg, pg_temp
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

  -- No active scope: return empty set (do not match all Role2Node scopes).
  IF v_sess.active_scope_id IS NULL THEN
    RETURN;
  END IF;

  RETURN QUERY
  WITH effective_roles AS (
    SELECT ur."RoleId"::int AS role_id
    FROM portal."UserRoles" ur
    WHERE ur."UserId" = v_sess.user_id
    UNION
    SELECT DISTINCT g."RoleID"::int AS role_id
    FROM "RBAC"."UserRoleGrants" g
    INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
    WHERE g."UserID" = v_sess.user_id
      AND g."Active"
      AND (
        COALESCE(r."BypassScope", false)
        OR g."ScopeID" = v_sess.active_scope_id
      )
    UNION
    SELECT er.role_id::int AS role_id
    FROM "RBAC".usp_session_get_effective_roles_v2(v_sess.session_id) er
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
      n."SortPath"::text AS sort_path
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
    COALESCE(NULLIF(btrim(ni."FrameKey"), ''), 'view')::text AS presentation_kind
  FROM visible_tree vt
  LEFT JOIN portal."NodeInfos" ni ON ni."Id" = vt.info_id
  ORDER BY vt.sort_path, vt.node_id;
END;
$$;
