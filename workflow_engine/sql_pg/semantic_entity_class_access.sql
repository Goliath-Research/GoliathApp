/*
  Class read access for semantic entities that map to a Meta class.

  Once portal.semantic_entity.meta_class_id is set, running the entity's requests also requires
  Meta class read access in the active scope. "Meta".sp_grant_semantic_entity_class_read(namespace)
  grants that read access (portal.sp_upsert_class_role_access, effect allow) to every role that can
  run one of the entity's requests today: the request has no required permission, the role holds it,
  or the role bypasses scope. It grants in each active scope where the role is granted (every
  active scope for a bypass role). It never overrides an explicit deny and never removes access.

  portal.fn_semantic_entity_class_read_gaps(namespace) lists the active (user, scope, request)
  combinations where a user can run a request today but has no class read; empty means nobody lost access.
*/

CREATE OR REPLACE FUNCTION portal.fn_semantic_entity_request_role_scopes(p_namespace text)
RETURNS TABLE (entity_id integer, class_id integer, request_code text, role_id integer, scope_id integer)
LANGUAGE sql
STABLE
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT DISTINCT e.id, e.meta_class_id, r.request_code, ro."ID", s."ScopeID"
  FROM portal.semantic_entity e
  JOIN portal.semantic_request r ON r.entity_id = e.id
  CROSS JOIN "RBAC"."Roles" ro
  JOIN "RBAC"."Scopes" s ON s."Active"
  WHERE e.meta_class_id IS NOT NULL
    AND (p_namespace IS NULL OR e.namespace = p_namespace)
    AND (
      r.required_permission IS NULL
      OR COALESCE(ro."BypassScope", false)
      OR EXISTS (
        SELECT 1 FROM "RBAC"."Role_Permissions" rp JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
        WHERE rp."RoleID" = ro."ID" AND p."Name" = r.required_permission
      )
    )
    AND EXISTS (
      SELECT 1 FROM "RBAC"."UserRoleGrants" g
      WHERE g."RoleID" = ro."ID" AND g."Active"
        AND (COALESCE(ro."BypassScope", false) OR g."ScopeID" = s."ScopeID")
    );
$$;

CREATE OR REPLACE FUNCTION "Meta".sp_grant_semantic_entity_class_read(p_namespace text)
RETURNS TABLE (class_name text, role_name text, scope_id integer, result text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  r record;
  v_effect text;
BEGIN
  FOR r IN
    SELECT DISTINCT x.class_id, x.role_id, x.scope_id, c."Name"::text AS cname, ro."Name"::text AS rname
    FROM portal.fn_semantic_entity_request_role_scopes(p_namespace) x
    JOIN "Meta"."Classes" c ON c."ID" = x.class_id
    JOIN "RBAC"."Roles" ro ON ro."ID" = x.role_id
    ORDER BY cname, rname, x.scope_id
  LOOP
    v_effect := portal.fn_meta_class_role_effect(r.scope_id, r.role_id, r.class_id, 'read');
    IF v_effect = 'deny' THEN
      RETURN QUERY SELECT r.cname, r.rname, r.scope_id, 'kept deny'::text;
    ELSIF v_effect = 'allow' THEN
      RETURN QUERY SELECT r.cname, r.rname, r.scope_id, 'already allowed'::text;
    ELSE
      PERFORM portal.sp_upsert_class_role_access(r.scope_id, r.role_id, r.class_id, 'read', 'allow');
      RETURN QUERY SELECT r.cname, r.rname, r.scope_id, 'granted'::text;
    END IF;
  END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION "Meta".sp_grant_semantic_entity_class_read(text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION portal.fn_semantic_entity_class_read_gaps(p_namespace text)
RETURNS TABLE (user_id integer, scope_id integer, request_code text, class_name text)
LANGUAGE sql
STABLE
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
  SELECT DISTINCT g."UserID", x.scope_id, x.request_code, c."Name"::text
  FROM portal.fn_semantic_entity_request_role_scopes(p_namespace) x
  JOIN "RBAC"."Roles" ro ON ro."ID" = x.role_id
  JOIN "RBAC"."UserRoleGrants" g
    ON g."RoleID" = x.role_id AND g."Active"
   AND (COALESCE(ro."BypassScope", false) OR g."ScopeID" = x.scope_id)
  JOIN "RBAC"."Users" u ON u."ID" = g."UserID" AND u."Active" = 1
  JOIN "Meta"."Classes" c ON c."ID" = x.class_id
  WHERE NOT portal.fn_meta_effective_class_action(g."UserID", x.scope_id, x.class_id, 'read');
$$;
