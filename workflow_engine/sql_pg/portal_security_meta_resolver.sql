/*
  Security enforcement reads Meta-backed grant cache (refresh after migrate / security writes).
*/

CREATE MATERIALIZED VIEW IF NOT EXISTS portal.mv_security_effective_grants AS
SELECT
  c.grant_obj_id,
  c.user_id,
  c.role_id,
  c.scope_id,
  c.bypass_scope
FROM portal.security_grant_cache c
WHERE c.active AND c.revoked_at_utc IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS "UX_portal_mv_security_effective_grants"
  ON portal.mv_security_effective_grants (grant_obj_id);

CREATE INDEX IF NOT EXISTS "IX_portal_mv_security_effective_grants_user_scope"
  ON portal.mv_security_effective_grants (user_id, scope_id);

CREATE OR REPLACE FUNCTION portal.sp_security_meta_refresh_cache()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_class_grant int;
BEGIN
  SELECT c."ID" INTO v_class_grant FROM "Meta"."Classes" c WHERE c."Name" = 'platform/RoleGrant';

  TRUNCATE portal.security_grant_cache;

  IF v_class_grant IS NULL THEN
    INSERT INTO portal.security_grant_cache (
      grant_obj_id, user_id, role_id, scope_id, active, revoked_at_utc, bypass_scope
    )
    SELECT
      g."ID",
      g."UserID",
      g."RoleID",
      g."ScopeID",
      g."Active",
      g."RevokedAtUtc",
      COALESCE(r."BypassScope", false)
    FROM "RBAC"."UserRoleGrants" g
    INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
    WHERE g."ScopeID" IS NOT NULL;
    RETURN;
  END IF;

  INSERT INTO portal.security_grant_cache (
    grant_obj_id, user_id, role_id, scope_id, active, revoked_at_utc, bypass_scope
  )
  SELECT DISTINCT ON ((ov."Data"->>'LegacyGrantId')::bigint)
    ov."ObjID",
    (ov."Data"->>'LegacyUserId')::int,
    (ov."Data"->>'LegacyRoleId')::int,
    (ov."Data"->>'LegacyScopeId')::int,
    COALESCE((ov."Data"->>'Active')::boolean, false),
    CASE
      WHEN ov."Data"->>'RevokedAtUtc' IS NULL OR btrim(ov."Data"->>'RevokedAtUtc') = '' THEN NULL
      ELSE (ov."Data"->>'RevokedAtUtc')::timestamptz
    END,
    COALESCE(ro."BypassScope", false)
  FROM "Meta"."ObjValues" ov
  LEFT JOIN "RBAC"."Roles" ro ON ro."ID" = (ov."Data"->>'LegacyRoleId')::int
  WHERE ov."ClassID" = v_class_grant
    AND (ov."Data"->>'LegacyScopeId') IS NOT NULL
    AND (ov."Data"->>'LegacyGrantId') ~ '^[0-9]+$'
  ORDER BY (ov."Data"->>'LegacyGrantId')::bigint, ov."ObjID" DESC;

  -- Stack B: grants created after migrate may exist only in RBAC until mirrored to Meta.
  INSERT INTO portal.security_grant_cache (
    grant_obj_id, user_id, role_id, scope_id, active, revoked_at_utc, bypass_scope
  )
  SELECT
    g."ID",
    g."UserID",
    g."RoleID",
    g."ScopeID",
    g."Active",
    g."RevokedAtUtc",
    COALESCE(r."BypassScope", false)
  FROM "RBAC"."UserRoleGrants" g
  INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
  WHERE g."ScopeID" IS NOT NULL
    AND g."Active"
    AND g."RevokedAtUtc" IS NULL
    AND NOT EXISTS (
      SELECT 1
      FROM portal.security_grant_cache c
      WHERE c.grant_obj_id = g."ID"
         OR (
           c.user_id = g."UserID"
           AND c.role_id = g."RoleID"
           AND c.scope_id = g."ScopeID"
         )
    );

  REFRESH MATERIALIZED VIEW portal.mv_security_effective_grants;
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
  SELECT DISTINCT role_id
  FROM (
    SELECT g.role_id
    FROM portal.mv_security_effective_grants g
    WHERE g.user_id = p_user_id
      AND (
        g.bypass_scope
        OR g.scope_id = p_scope_id
      )
      AND EXISTS (
        SELECT 1
        FROM "RBAC"."UserRoleGrants" rg
        WHERE rg."UserID" = g.user_id
          AND rg."RoleID" = g.role_id
          AND rg."ScopeID" = g.scope_id
          AND rg."Active"
          AND rg."RevokedAtUtc" IS NULL
      )
    UNION
    SELECT g."RoleID" AS role_id
    FROM "RBAC"."UserRoleGrants" g
    INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
    WHERE g."UserID" = p_user_id
      AND g."Active"
      AND g."RevokedAtUtc" IS NULL
      AND (
        COALESCE(r."BypassScope", false)
        OR g."ScopeID" = p_scope_id
      )
  ) grants;
$$;

CREATE OR REPLACE FUNCTION portal.fn_security_role_has_permission(
  p_role_id integer,
  p_permission text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM "RBAC"."Role_Permissions" rp
    INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
    WHERE rp."RoleID" = p_role_id
      AND p."Name" = p_permission
  )
  OR EXISTS (
    SELECT 1
    FROM "Meta"."ObjValues" perm
    INNER JOIN "Meta"."ObjValues" role_perm ON role_perm."ObjID" = p_role_id
    WHERE perm."ClassID" = (SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Permission' LIMIT 1)
      AND perm."Data"->>'PermissionName' = p_permission
      AND false
  );
$$;

CREATE OR REPLACE FUNCTION portal.fn_security_meta_user_legacy_map_ok(p_user_id integer)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM portal.security_meta_legacy_map m
    INNER JOIN "Meta"."ObjValues" ov ON ov."ObjID" = m.meta_obj_id
    INNER JOIN "Meta"."Classes" c ON c."ID" = ov."ClassID"
    WHERE m.legacy_kind = 'user'
      AND m.legacy_id = p_user_id
      AND c."Name" = 'platform/User'
      AND (ov."Data"->>'LegacyUserId')::int = p_user_id
  );
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
BEGIN
  SELECT r."ID" INTO v_admin_role FROM "RBAC"."Roles" r WHERE r."Name" = 'organization_admin' LIMIT 1;

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
  SELECT role_id FROM portal.fn_security_user_grant_role_ids(p_user_id, p_scope_id);
$$;

SELECT portal.sp_security_meta_migrate_from_legacy();
SELECT portal.sp_security_meta_refresh_cache();
