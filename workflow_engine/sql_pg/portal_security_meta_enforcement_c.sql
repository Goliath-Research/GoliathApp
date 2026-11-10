/*
  PR C: enforcement reads Meta security objects only (grants cache, identities, invitations).
  Legacy RBAC tables are not read on hot paths after migrate; refresh runs on security writes.
*/

CREATE OR REPLACE FUNCTION portal.fn_security_meta_class_ids()
RETURNS TABLE (class_id integer, class_name text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
  SELECT c."ID", c."Name"::text
  FROM "Meta"."Classes" c
  WHERE c."Name" IN (
    'platform/User',
    'platform/Role',
    'platform/Permission',
    'platform/RoleGrant',
    'platform/ExternalIdentity',
    'platform/Invitation'
  );
$$;

CREATE OR REPLACE FUNCTION portal.fn_security_meta_is_security_class(p_class_id integer)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM portal.fn_security_meta_class_ids() s WHERE s.class_id = p_class_id
  );
$$;

CREATE OR REPLACE FUNCTION portal.fn_security_meta_bypass_scope(p_role_id integer)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
  SELECT COALESCE(
    (
      SELECT (ov."Data"->>'BypassScope')::boolean
      FROM "Meta"."Classes" c
      INNER JOIN "Meta"."ObjValues" ov ON ov."ClassID" = c."ID"
      WHERE c."Name" = 'platform/Role'
        AND (ov."Data"->>'LegacyRoleId')::int = p_role_id
      LIMIT 1
    ),
    (
      SELECT r."BypassScope"
      FROM "RBAC"."Roles" r
      WHERE r."ID" = p_role_id
      LIMIT 1
    ),
    false
  );
$$;

CREATE TABLE IF NOT EXISTS portal.security_role_permission_cache (
  role_id integer NOT NULL,
  permission_name text NOT NULL,
  PRIMARY KEY (role_id, permission_name)
);

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
  IF v_class_grant IS NULL THEN
    RAISE EXCEPTION 'platform/RoleGrant class is required for security enforcement';
  END IF;

  TRUNCATE portal.security_grant_cache;

  INSERT INTO portal.security_grant_cache (
    grant_obj_id, user_id, role_id, scope_id, active, revoked_at_utc, bypass_scope
  )
  SELECT
    ov."ObjID",
    (ov."Data"->>'LegacyUserId')::int,
    (ov."Data"->>'LegacyRoleId')::int,
    CASE
      WHEN COALESCE(ov."Data"->>'GrantType', '') = 'GLOBAL' THEN 0
      ELSE (ov."Data"->>'LegacyScopeId')::int
    END,
    COALESCE((ov."Data"->>'Active')::boolean, false),
    CASE
      WHEN ov."Data"->>'RevokedAtUtc' IS NULL OR btrim(ov."Data"->>'RevokedAtUtc') = '' THEN NULL
      ELSE (ov."Data"->>'RevokedAtUtc')::timestamptz
    END,
    COALESCE(portal.fn_security_meta_bypass_scope((ov."Data"->>'LegacyRoleId')::int), false)
  FROM "Meta"."ObjValues" ov
  WHERE ov."ClassID" = v_class_grant
    AND (
      (ov."Data"->>'LegacyScopeId') IS NOT NULL AND btrim(ov."Data"->>'LegacyScopeId') <> ''
      OR COALESCE(ov."Data"->>'GrantType', '') = 'GLOBAL'
    );

  DELETE FROM portal.security_role_permission_cache;
  INSERT INTO portal.security_role_permission_cache (role_id, permission_name)
  SELECT rp."RoleID", p."Name"
  FROM "RBAC"."Role_Permissions" rp
  INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID";

  REFRESH MATERIALIZED VIEW portal.mv_security_effective_grants;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_security_role_has_permission(
  p_role_id integer,
  p_permission text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM portal.security_role_permission_cache rpc
    WHERE rpc.role_id = p_role_id
      AND rpc.permission_name = p_permission
  );
$$;

CREATE OR REPLACE FUNCTION portal.fn_security_meta_user_by_email(p_email text)
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
  SELECT (ov."Data"->>'LegacyUserId')::int
  FROM "Meta"."Classes" c
  INNER JOIN "Meta"."ObjValues" ov ON ov."ClassID" = c."ID"
  WHERE c."Name" = 'platform/User'
    AND lower(btrim(ov."Data"->>'Email')) = lower(btrim(p_email))
    AND COALESCE((ov."Data"->>'Active')::boolean, false)
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION portal.fn_security_meta_external_identity_user(
  p_provider_id integer,
  p_subject text
)
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
  SELECT (ov."Data"->>'LegacyUserId')::int
  FROM "Meta"."Classes" c
  INNER JOIN "Meta"."ObjValues" ov ON ov."ClassID" = c."ID"
  WHERE c."Name" = 'platform/ExternalIdentity'
    AND (ov."Data"->>'ProviderId')::int = p_provider_id
    AND btrim(ov."Data"->>'Subject') = btrim(p_subject)
    AND COALESCE((ov."Data"->>'Active')::boolean, false)
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION portal.sp_resolve_user_by_scope_identity_meta(
  p_scope_id integer,
  p_issuer text,
  p_subject text
)
RETURNS TABLE (provider_id integer, user_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", "Meta", pg_temp
AS $$
DECLARE
  v_provider_id int;
  v_user_id int;
BEGIN
  v_provider_id := portal.fn_scope_provider_id_for_issuer(p_scope_id, p_issuer);
  IF v_provider_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'issuer does not match a scope identity provider');
  END IF;

  v_user_id := portal.fn_security_meta_external_identity_user(v_provider_id, p_subject);
  IF v_user_id IS NULL THEN
    RETURN QUERY SELECT v_provider_id, NULL::integer;
    RETURN;
  END IF;

  RETURN QUERY SELECT v_provider_id, v_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION "RBAC".spresolveuserbyscopeidentity(
  p_scope_id int,
  p_issuer text,
  p_subject text
)
RETURNS TABLE(provider_id int, user_id int)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", "Meta", pg_temp
AS $$
  SELECT * FROM portal.sp_resolve_user_by_scope_identity_meta(p_scope_id, p_issuer, p_subject);
$$;

CREATE OR REPLACE FUNCTION portal.fn_security_meta_gate_mutation(
  p_session_token text,
  p_class_id integer,
  p_target_user_id integer DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_sess record;
BEGIN
  IF NOT portal.fn_security_meta_is_security_class(p_class_id) THEN
    RETURN;
  END IF;

  SELECT * INTO v_sess FROM portal.fn_session_resolve(p_session_token) LIMIT 1;
  IF v_sess.session_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS401', 'session denied');
  END IF;

  IF NOT portal.fn_session_has_permission(
    v_sess.session_id, v_sess.user_id, v_sess.active_scope_id, 'platform.security.admin'
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'platform security admin required for security class mutation');
  END IF;

  IF p_target_user_id IS NOT NULL AND p_target_user_id = v_sess.user_id THEN
    PERFORM portal.fn_semantic_raise('GS403', 'cannot mutate your own security grants or identity');
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.trg_security_meta_refresh_cache()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", pg_temp
AS $$
BEGIN
  IF portal.fn_security_meta_is_security_class(NEW."ClassID") THEN
    PERFORM portal.sp_security_meta_refresh_cache();
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_SecurityMeta_ObjValues_Refresh" ON "Meta"."ObjValues";
CREATE TRIGGER "TR_SecurityMeta_ObjValues_Refresh"
  AFTER INSERT OR UPDATE OF "Data"
  ON "Meta"."ObjValues"
  FOR EACH ROW
  EXECUTE FUNCTION portal.trg_security_meta_refresh_cache();

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
  v_target_uid int;
BEGIN
  v_class_id := portal.sp_session_meta_resolve_class(p_session_token, p_class_name);
  v_target_uid := NULLIF((p_document->>'LegacyUserId')::int, 0);
  PERFORM portal.fn_security_meta_gate_mutation(p_session_token, v_class_id, v_target_uid);

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
    IF NOT portal.fn_meta_effective_class_action_explicit(
      v_ctx.user_id, v_ctx.active_scope_id, v_class_id, 'create', v_ctx.session_id
    ) THEN
      PERFORM portal.fn_semantic_raise('GS403', 'meta permission denied');
    END IF;
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
  v_class_id int;
  v_doc jsonb;
  v_target_uid int;
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

  SELECT o."ClassID" INTO v_class_id FROM "Meta"."Objs" o WHERE o."ID" = p_obj_id;
  v_target_uid := NULLIF((p_document->>'LegacyUserId')::int, 0);
  PERFORM portal.fn_security_meta_gate_mutation(p_session_token, v_class_id, v_target_uid);

  v_doc := portal.fn_session_meta_strip_tenancy_keys(p_document);
  PERFORM "Meta".sp_obj_update(p_obj_id, COALESCE(v_doc, '{}'::jsonb));
END;
$$;

DO $seed_sec_acl$
DECLARE
  v_scope int;
  v_admin_role int;
  v_class_id int;
  v_cls record;
BEGIN
  SELECT MIN(s."ScopeID") INTO v_scope FROM "RBAC"."Scopes" s WHERE s."Active" = true;
  SELECT r."ID" INTO v_admin_role FROM "RBAC"."Roles" r WHERE r."Name" = 'organization_admin' LIMIT 1;
  IF v_scope IS NULL OR v_admin_role IS NULL THEN
    RETURN;
  END IF;

  FOR v_cls IN SELECT class_id FROM portal.fn_security_meta_class_ids()
  LOOP
    v_class_id := v_cls.class_id;
    INSERT INTO portal."MetaClassRoleAccess" ("ScopeID", "RoleID", "ClassID", "Action", "Effect")
    SELECT v_scope, v_admin_role, v_class_id, act, 'allow'
    FROM unnest(ARRAY['create', 'update', 'delete', 'read']::text[]) AS act
    ON CONFLICT ON CONSTRAINT "UQ_MetaClassRoleAccess"
    DO UPDATE SET "Effect" = 'allow';
  END LOOP;
END
$seed_sec_acl$;

DROP FUNCTION IF EXISTS portal.sp_session_list_users_admin(text);

CREATE OR REPLACE FUNCTION portal.sp_session_list_users_admin(p_session_token text)
RETURNS TABLE (
  user_id int,
  full_name text,
  email text,
  active int,
  scoped_role_count int,
  active_roles_summary text,
  sign_in_status text,
  identity_provider_name text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_provider_count int;
  v_user_class int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  SELECT c."ID" INTO v_user_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/User';

  SELECT COUNT(*)::int INTO v_provider_count
  FROM "RBAC"."ScopeIdentityProviders" sip
  WHERE sip."ScopeID" = v_ctx.active_scope_id AND sip."Active" = true;

  RETURN QUERY
  WITH scope_providers AS (
    SELECT ip."ProviderID", ip."Name" AS provider_name
    FROM "RBAC"."ScopeIdentityProviders" sip
    INNER JOIN "RBAC"."IdentityProviders" ip ON ip."ProviderID" = sip."ProviderID"
    WHERE sip."ScopeID" = v_ctx.active_scope_id
      AND sip."Active" = true
      AND ip."Active" = true
  ),
  primary_provider AS (
    SELECT sp."ProviderID" AS provider_id, sp.provider_name
    FROM scope_providers sp
    ORDER BY sp.provider_name
    LIMIT 1
  )
  SELECT
    (uov."Data"->>'LegacyUserId')::int,
    uov."Data"->>'FullName',
    uov."Data"->>'Email',
    CASE WHEN COALESCE((uov."Data"->>'Active')::boolean, false) THEN 1 ELSE 0 END,
    (
      SELECT COUNT(*)::int
      FROM portal.mv_security_effective_grants g
      WHERE g.user_id = (uov."Data"->>'LegacyUserId')::int
        AND g.scope_id = v_ctx.active_scope_id
    ),
    (
      SELECT string_agg(rn."Data"->>'RoleName', ', ' ORDER BY rn."Data"->>'RoleName')
      FROM portal.mv_security_effective_grants g
      INNER JOIN "Meta"."ObjValues" rn ON rn."ClassID" = (SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Role')
        AND (rn."Data"->>'LegacyRoleId')::int = g.role_id
      WHERE g.user_id = (uov."Data"->>'LegacyUserId')::int
        AND g.scope_id = v_ctx.active_scope_id
    )::text,
    CASE
      WHEN v_provider_count = 0 THEN 'no_provider'
      WHEN EXISTS (
        SELECT 1
        FROM "Meta"."ObjValues" eid
        WHERE eid."ClassID" = (SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/ExternalIdentity')
          AND (eid."Data"->>'LegacyUserId')::int = (uov."Data"->>'LegacyUserId')::int
          AND COALESCE((eid."Data"->>'Active')::boolean, false)
      ) THEN 'linked'
      WHEN COALESCE((uov."Data"->>'Active')::boolean, false)
           AND NULLIF(btrim(uov."Data"->>'Email'), '') IS NOT NULL THEN 'awaiting_first_sign_in'
      ELSE 'inactive'
    END::text,
    (SELECT pp.provider_name FROM primary_provider pp)::text
  FROM "Meta"."ObjValues" uov
  WHERE uov."ClassID" = v_user_class
  ORDER BY 1;
END;
$$;

DROP FUNCTION IF EXISTS portal.sp_session_list_user_role_grants_scoped(text, integer);

CREATE OR REPLACE FUNCTION portal.sp_session_list_user_role_grants_scoped(
  p_session_token text,
  p_target_user_id integer
)
RETURNS TABLE (
  grant_id bigint,
  user_id integer,
  role_id integer,
  role_name text,
  grant_type text,
  scope_id integer,
  scope_name text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_grant_class int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  SELECT c."ID" INTO v_grant_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/RoleGrant';

  RETURN QUERY
  SELECT
    (gov."Data"->>'LegacyGrantId')::bigint,
    (gov."Data"->>'LegacyUserId')::int,
    (gov."Data"->>'LegacyRoleId')::int,
    rov."Data"->>'RoleName',
    gov."Data"->>'GrantType',
    (gov."Data"->>'LegacyScopeId')::int,
    s."Name"::text
  FROM "Meta"."ObjValues" gov
  INNER JOIN "Meta"."ObjValues" rov
    ON rov."ClassID" = (SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Role' LIMIT 1)
   AND (rov."Data"->>'LegacyRoleId')::int = (gov."Data"->>'LegacyRoleId')::int
  LEFT JOIN "RBAC"."Scopes" s ON s."ScopeID" = (gov."Data"->>'LegacyScopeId')::int
  WHERE gov."ClassID" = v_grant_class
    AND (gov."Data"->>'LegacyUserId')::int = p_target_user_id
    AND (gov."Data"->>'LegacyScopeId')::int = v_ctx.active_scope_id
    AND COALESCE((gov."Data"->>'Active')::boolean, false)
    AND (
      gov."Data"->>'RevokedAtUtc' IS NULL OR btrim(gov."Data"->>'RevokedAtUtc') = ''
    )
  ORDER BY rov."Data"->>'RoleName', (gov."Data"->>'LegacyGrantId')::bigint;
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
  v_grant_obj int;
  v_grant_class int;
  v_user_id int;
  v_role_id int;
  v_scope_id int;
  v_role_name text;
  v_org_admin_id int;
  v_peer_admin_count int;
  v_now text;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  SELECT c."ID" INTO v_grant_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/RoleGrant';

  SELECT ov."ObjID",
         (ov."Data"->>'LegacyUserId')::int,
         (ov."Data"->>'LegacyRoleId')::int,
         (ov."Data"->>'LegacyScopeId')::int
  INTO v_grant_obj, v_user_id, v_role_id, v_scope_id
  FROM "Meta"."ObjValues" ov
  WHERE ov."ClassID" = v_grant_class
    AND (ov."Data"->>'LegacyGrantId')::bigint = p_grant_id
    AND COALESCE((ov."Data"->>'Active')::boolean, false)
  LIMIT 1;

  IF v_grant_obj IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'role grant not found');
  END IF;

  IF v_scope_id IS DISTINCT FROM v_ctx.active_scope_id THEN
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
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
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

CREATE OR REPLACE FUNCTION portal.sp_security_meta_upsert_role_grant_from_rbac(p_grant_id bigint)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_class_grant int;
  v_obj int;
  v_doc jsonb;
  g record;
BEGIN
  SELECT c."ID" INTO v_class_grant FROM "Meta"."Classes" c WHERE c."Name" = 'platform/RoleGrant';
  IF v_class_grant IS NULL THEN
    RETURN;
  END IF;

  SELECT * INTO g FROM "RBAC"."UserRoleGrants" WHERE "ID" = p_grant_id;
  IF g."ID" IS NULL THEN
    RETURN;
  END IF;

  SELECT m.meta_obj_id INTO v_obj
  FROM portal.security_meta_legacy_map m
  WHERE m.legacy_kind = 'role_grant' AND m.legacy_id = g."ID";

  v_doc := jsonb_build_object(
    'Label', format('grant %s', g."ID"),
    'Active', g."Active",
    'GrantType', g."GrantType",
    'GrantedAtUtc', to_char(g."GrantedAtUtc" AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'RevokedAtUtc', CASE
      WHEN g."RevokedAtUtc" IS NULL THEN NULL
      ELSE to_char(g."RevokedAtUtc" AT TIME ZONE 'utc', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
    END,
    'LegacyGrantId', g."ID",
    'LegacyUserId', g."UserID",
    'LegacyRoleId', g."RoleID",
    'LegacyScopeId', g."ScopeID"
  );

  IF v_obj IS NULL THEN
    v_obj := "Meta".sp_obj_insert(v_class_grant, v_doc);
    PERFORM portal.sp_security_meta_upsert_map('role_grant', g."ID", v_obj);
  ELSE
    UPDATE "Meta"."ObjValues" ov
    SET "Data" = v_doc
    WHERE ov."ObjID" = v_obj AND ov."ClassID" = v_class_grant;
  END IF;

  PERFORM portal.sp_security_meta_refresh_cache();
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_organization_set_admin(
  p_organization_id integer,
  p_user_id integer
)
RETURNS TABLE (grant_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", "Meta", pg_temp
AS $$
DECLARE
  v_scope_id integer;
  v_role_id integer;
  v_grant_id bigint;
BEGIN
  IF p_organization_id IS NULL OR p_organization_id <= 0 THEN
    RAISE EXCEPTION 'organization_id is required';
  END IF;
  IF p_user_id IS NULL OR p_user_id <= 0 THEN
    RAISE EXCEPTION 'user_id is required';
  END IF;

  SELECT s."ScopeID"
  INTO v_scope_id
  FROM "RBAC"."Scopes" s
  WHERE s."ScopeType" = 'organization'
    AND s."OrganizationID" = p_organization_id
    AND s."Active"
  ORDER BY s."ScopeID"
  LIMIT 1;

  IF v_scope_id IS NULL THEN
    RAISE EXCEPTION 'no active RBAC scope for organization %', p_organization_id;
  END IF;

  SELECT r."ID" INTO v_role_id
  FROM "RBAC"."Roles" r
  WHERE r."Name" = 'organization_admin';

  IF v_role_id IS NULL THEN
    RAISE EXCEPTION 'built-in role organization_admin is missing';
  END IF;

  PERFORM portal.sp_organization_add_member(p_organization_id, p_user_id);

  SELECT g."ID"
  INTO v_grant_id
  FROM "RBAC"."UserRoleGrants" g
  WHERE g."UserID" = p_user_id
    AND g."RoleID" = v_role_id
    AND g."GrantType" = 'SCOPED'
    AND g."ScopeID" = v_scope_id
    AND g."Active"
  ORDER BY g."ID"
  LIMIT 1;

  IF v_grant_id IS NULL THEN
    INSERT INTO "RBAC"."UserRoleGrants" (
      "UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc"
    )
    VALUES (
      p_user_id, v_role_id, 'SCOPED', v_scope_id, true, now() AT TIME ZONE 'utc'
    )
    RETURNING "ID" INTO v_grant_id;
  END IF;

  PERFORM portal.sp_security_meta_upsert_role_grant_from_rbac(v_grant_id);

  RETURN QUERY SELECT v_grant_id;
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

CREATE OR REPLACE FUNCTION portal.sp_security_meta_upsert_external_identity_from_rbac(p_external_identity_id integer)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
DECLARE
  v_class_ext int;
  v_obj int;
  v_doc jsonb;
  ei record;
BEGIN
  SELECT c."ID" INTO v_class_ext FROM "Meta"."Classes" c WHERE c."Name" = 'platform/ExternalIdentity';
  IF v_class_ext IS NULL THEN
    RETURN;
  END IF;

  SELECT * INTO ei FROM "RBAC"."ExternalIdentities" WHERE "ID" = p_external_identity_id;
  IF ei."ID" IS NULL THEN
    RETURN;
  END IF;

  SELECT m.meta_obj_id INTO v_obj
  FROM portal.security_meta_legacy_map m
  WHERE m.legacy_kind = 'external_identity' AND m.legacy_id = ei."ID";

  v_doc := jsonb_build_object(
    'Label', format('%s@%s', ei."Subject", ei."ProviderID"),
    'ProviderId', ei."ProviderID",
    'Subject', ei."Subject",
    'EmailSnapshot', ei."EmailSnapshot",
    'Active', ei."Active",
    'LegacyExternalIdentityId', ei."ID",
    'LegacyUserId', ei."UserID"
  );

  IF v_obj IS NULL THEN
    v_obj := "Meta".sp_obj_insert(v_class_ext, v_doc);
    PERFORM portal.sp_security_meta_upsert_map('external_identity', ei."ID", v_obj);
  ELSE
    UPDATE "Meta"."ObjValues" ov
    SET "Data" = v_doc
    WHERE ov."ObjID" = v_obj AND ov."ClassID" = v_class_ext;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.trg_rbac_user_role_grant_sync_meta()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
BEGIN
  PERFORM portal.sp_security_meta_upsert_role_grant_from_rbac(NEW."ID");
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION portal.trg_rbac_role_permission_sync_meta()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
BEGIN
  PERFORM portal.sp_security_meta_refresh_cache();
  RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE OR REPLACE FUNCTION portal.trg_rbac_external_identity_sync_meta()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "Meta", "RBAC", pg_temp
AS $$
BEGIN
  PERFORM portal.sp_security_meta_upsert_external_identity_from_rbac(NEW."ID");
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_UserRoleGrants_SecurityMeta" ON "RBAC"."UserRoleGrants";
CREATE TRIGGER "TR_UserRoleGrants_SecurityMeta"
  AFTER INSERT OR UPDATE OF "Active", "RevokedAtUtc", "RoleID", "ScopeID", "UserID"
  ON "RBAC"."UserRoleGrants"
  FOR EACH ROW
  EXECUTE FUNCTION portal.trg_rbac_user_role_grant_sync_meta();

DROP TRIGGER IF EXISTS "TR_Role_Permissions_SecurityMeta" ON "RBAC"."Role_Permissions";
CREATE TRIGGER "TR_Role_Permissions_SecurityMeta"
  AFTER INSERT OR DELETE OR UPDATE
  ON "RBAC"."Role_Permissions"
  FOR EACH ROW
  EXECUTE FUNCTION portal.trg_rbac_role_permission_sync_meta();

DROP TRIGGER IF EXISTS "TR_ExternalIdentities_SecurityMeta" ON "RBAC"."ExternalIdentities";
CREATE TRIGGER "TR_ExternalIdentities_SecurityMeta"
  AFTER INSERT OR UPDATE OF "Active", "ProviderID", "Subject", "UserID"
  ON "RBAC"."ExternalIdentities"
  FOR EACH ROW
  EXECUTE FUNCTION portal.trg_rbac_external_identity_sync_meta();

CREATE OR REPLACE FUNCTION portal.fn_session_user_selectable_role_ids(
  p_user_id integer,
  p_scope_id integer
)
RETURNS TABLE (role_id integer)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  SELECT role_id FROM portal.fn_security_user_grant_role_ids(p_user_id, p_scope_id);
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
SET search_path = portal, pg_temp
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
      AND portal.fn_security_role_has_permission(
        portal.fn_session_active_role_id(p_session_id),
        p_permission
      )
    );
$$;
