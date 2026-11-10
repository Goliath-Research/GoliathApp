/*
  Scoped invitations, first-sign-in external identity linking, and admin user sign-in status.
*/

CREATE TABLE IF NOT EXISTS portal.external_identity_link_audit (
  audit_id bigserial PRIMARY KEY,
  scope_id integer NOT NULL,
  provider_id integer NOT NULL,
  user_id integer NOT NULL,
  subject text NOT NULL,
  email_snapshot text NOT NULL,
  link_kind text NOT NULL,
  invitation_id bigint NULL,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE OR REPLACE FUNCTION portal.fn_auth_snapshot_claims(p_snapshot text)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN p_snapshot IS NULL OR btrim(p_snapshot) = '' THEN '{}'::jsonb
    WHEN left(btrim(p_snapshot), 1) = '{' THEN p_snapshot::jsonb
    ELSE '{}'::jsonb
  END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_auth_snapshot_email(p_snapshot text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT lower(btrim(COALESCE(
    NULLIF(portal.fn_auth_snapshot_claims(p_snapshot)->>'email', ''),
    NULLIF(portal.fn_auth_snapshot_claims(p_snapshot)->>'preferred_username', ''),
    NULLIF(portal.fn_auth_snapshot_claims(p_snapshot)->>'upn', '')
  )));
$$;

CREATE OR REPLACE FUNCTION portal.fn_auth_snapshot_full_name(p_snapshot text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT NULLIF(btrim(COALESCE(
    portal.fn_auth_snapshot_claims(p_snapshot)->>'name',
    portal.fn_auth_snapshot_claims(p_snapshot)->>'email'
  )), '');
$$;

CREATE OR REPLACE FUNCTION portal.fn_validate_invitation_email(p_email text)
RETURNS text
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v text := lower(btrim(p_email));
BEGIN
  IF v IS NULL OR v = '' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'email is required');
  END IF;
  IF v !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' THEN
    PERFORM portal.fn_semantic_raise('GS400', 'email format is invalid');
  END IF;
  RETURN v;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_resolve_scope_identity_provider(
  p_scope_id integer,
  p_provider_id integer DEFAULT NULL
)
RETURNS integer
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_count int;
  v_pid int;
BEGIN
  IF p_scope_id IS NULL OR p_scope_id <= 0 THEN
    PERFORM portal.fn_semantic_raise('GS403', 'scope is required');
  END IF;

  IF p_provider_id IS NOT NULL THEN
    IF NOT EXISTS (
      SELECT 1
      FROM "RBAC"."ScopeIdentityProviders" sip
      INNER JOIN "RBAC"."IdentityProviders" ip ON ip."ProviderID" = sip."ProviderID"
      WHERE sip."ScopeID" = p_scope_id
        AND sip."ProviderID" = p_provider_id
        AND sip."Active" = true
        AND ip."Active" = true
    ) THEN
      PERFORM portal.fn_semantic_raise('GS400', 'identity provider is not linked to this scope');
    END IF;
    RETURN p_provider_id;
  END IF;

  SELECT COUNT(*)::int, MIN(sip."ProviderID")
  INTO v_count, v_pid
  FROM "RBAC"."ScopeIdentityProviders" sip
  INNER JOIN "RBAC"."IdentityProviders" ip ON ip."ProviderID" = sip."ProviderID"
  WHERE sip."ScopeID" = p_scope_id
    AND sip."Active" = true
    AND ip."Active" = true;

  IF v_count = 0 THEN
    PERFORM portal.fn_semantic_raise('GS403', 'no identity provider is linked to this scope');
  ELSIF v_count > 1 THEN
    PERFORM portal.fn_semantic_raise('GS400', 'multiple identity providers linked; provider_id is required');
  END IF;

  RETURN v_pid;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_scope_provider_id_for_issuer(
  p_scope_id integer,
  p_issuer text
)
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT ip."ProviderID"
  FROM "RBAC"."ScopeIdentityProviders" sip
  INNER JOIN "RBAC"."IdentityProviders" ip ON ip."ProviderID" = sip."ProviderID"
  WHERE sip."ScopeID" = p_scope_id
    AND sip."Active" = true
    AND ip."Active" = true
    AND ip."Issuer" = btrim(p_issuer)
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION portal.fn_provider_email_allowed(
  p_provider_id integer,
  p_email text
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
  SELECT CASE
    WHEN ip."AllowedDomainPattern" IS NULL OR btrim(ip."AllowedDomainPattern") = '' THEN true
    ELSE right(lower(btrim(p_email)), length(lower(btrim(ip."AllowedDomainPattern"))) + 1)
         = '@' || lower(btrim(ip."AllowedDomainPattern"))
  END
  FROM "RBAC"."IdentityProviders" ip
  WHERE ip."ProviderID" = p_provider_id;
$$;

CREATE OR REPLACE FUNCTION portal.sp_scope_login_provision_identity(
  p_scope_id integer,
  p_issuer text,
  p_subject text,
  p_auth_subject_snapshot text DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", "Onboarding", "Contract", public, pg_temp
AS $$
DECLARE
  v_provider_id int;
  v_email text;
  v_full_name text;
  v_user_id int;
  v_bound_user int;
  v_existing_subject_user int;
  v_invitation_id bigint;
  v_role_id int;
  v_role_ok boolean;
BEGIN
  v_provider_id := portal.fn_scope_provider_id_for_issuer(p_scope_id, p_issuer);
  IF v_provider_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'issuer does not match a scope identity provider');
  END IF;

  SELECT ei."UserID" INTO v_existing_subject_user
  FROM "RBAC"."ExternalIdentities" ei
  WHERE ei."ProviderID" = v_provider_id
    AND ei."Subject" = btrim(p_subject)
    AND ei."Active" = true
  LIMIT 1;

  IF v_existing_subject_user IS NOT NULL THEN
    IF EXISTS (
      SELECT 1 FROM "RBAC"."Users" u
      WHERE u."ID" = v_existing_subject_user AND u."Active" = 1
    ) THEN
      RETURN;
    END IF;
    PERFORM portal.fn_semantic_raise('GS403', 'external identity subject is already linked');
  END IF;

  v_email := portal.fn_auth_snapshot_email(p_auth_subject_snapshot);
  IF v_email IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'verified email claim is required for first sign-in');
  END IF;

  IF NOT portal.fn_provider_email_allowed(v_provider_id, v_email) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'email domain does not match identity provider policy');
  END IF;

  SELECT i."InvitationID"
  INTO v_invitation_id
  FROM "Onboarding"."Invitations" i
  WHERE i."ScopeID" = p_scope_id
    AND i."Email" = v_email
    AND i."ExpectedProviderID" = v_provider_id
    AND i."Status" = 'PENDING'
    AND i."ExpiresAtUtc" >= (now() AT TIME ZONE 'utc')
  ORDER BY i."CreatedAtUtc" DESC
  LIMIT 1;

  v_full_name := COALESCE(portal.fn_auth_snapshot_full_name(p_auth_subject_snapshot), v_email);

  IF v_invitation_id IS NOT NULL THEN
    PERFORM "Onboarding".spacceptinvitation(
      v_invitation_id,
      btrim(p_issuer),
      btrim(p_subject),
      v_email,
      v_full_name
    );
    INSERT INTO portal.external_identity_link_audit (
      scope_id, provider_id, user_id, subject, email_snapshot, link_kind, invitation_id
    )
  SELECT p_scope_id, v_provider_id, ei."UserID", btrim(p_subject), v_email, 'invitation_accept', v_invitation_id
    FROM "RBAC"."ExternalIdentities" ei
    WHERE ei."ProviderID" = v_provider_id AND ei."Subject" = btrim(p_subject)
    LIMIT 1;
    RETURN;
  END IF;

  SELECT u."ID" INTO v_user_id
  FROM "RBAC"."Users" u
  WHERE lower(btrim(u.email)) = v_email AND u."Active" = 1
  LIMIT 1;

  IF v_user_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'external identity is not linked to a user for this scope');
  END IF;

  SELECT ei."UserID" INTO v_bound_user
  FROM "RBAC"."ExternalIdentities" ei
  WHERE ei."ProviderID" = v_provider_id
    AND ei."UserID" = v_user_id
    AND ei."Active" = true
  LIMIT 1;

  IF v_bound_user IS NOT NULL THEN
    IF EXISTS (
      SELECT 1 FROM "RBAC"."ExternalIdentities" ei
      WHERE ei."ProviderID" = v_provider_id
        AND ei."UserID" = v_user_id
        AND ei."Subject" = btrim(p_subject)
        AND ei."Active" = true
    ) THEN
      RETURN;
    END IF;
    PERFORM portal.fn_semantic_raise('GS403', 'user already has a different sign-in identity for this provider');
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM "RBAC"."Scopes" s
    INNER JOIN portal."OrganizationMembers" m ON m."OrganizationID" = s."OrganizationID"
    WHERE s."ScopeID" = p_scope_id AND m."UserID" = v_user_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM "RBAC"."UserRoleGrants" g
    WHERE g."UserID" = v_user_id AND g."ScopeID" = p_scope_id AND g."Active" = true
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'user is not provisioned for this organization scope');
  END IF;

  INSERT INTO "RBAC"."ExternalIdentities"
    ("UserID", "ProviderID", "Subject", "EmailSnapshot", "Active", "CreatedAtUtc", "LastLoginAtUtc")
  VALUES (
    v_user_id, v_provider_id, btrim(p_subject), v_email, true,
    now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc'
  );

  INSERT INTO portal.external_identity_link_audit (
    scope_id, provider_id, user_id, subject, email_snapshot, link_kind, invitation_id
  )
  VALUES (
    p_scope_id, v_provider_id, v_user_id, btrim(p_subject), v_email, 'admin_user_first_sign_in', NULL
  );
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_open_for_scope_identity(
  p_scope_id int,
  p_issuer text,
  p_subject text,
  p_auth_subject_snapshot text DEFAULT NULL
)
RETURNS TABLE (
  session_token text,
  session_id int,
  expires_at_utc timestamptz,
  user_id int,
  auth_provider_id int
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", "Onboarding", cfg, pg_temp
AS $$
DECLARE
  v_provider_id int;
  v_user_id int;
  v_open record;
BEGIN
  IF p_scope_id IS NULL OR p_scope_id <= 0 THEN
    PERFORM portal.fn_semantic_raise('GS403', 'scope is required for external login');
  END IF;
  IF NULLIF(btrim(p_issuer), '') IS NULL OR NULLIF(btrim(p_subject), '') IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'issuer and subject are required');
  END IF;

  SELECT r.provider_id, r.user_id
  INTO v_provider_id, v_user_id
  FROM "RBAC".spresolveuserbyscopeidentity(p_scope_id, btrim(p_issuer), btrim(p_subject)) r
  LIMIT 1;

  IF v_user_id IS NULL OR v_provider_id IS NULL THEN
    PERFORM portal.sp_scope_login_provision_identity(
      p_scope_id, p_issuer, p_subject, p_auth_subject_snapshot
    );
    SELECT r.provider_id, r.user_id
    INTO v_provider_id, v_user_id
    FROM "RBAC".spresolveuserbyscopeidentity(p_scope_id, btrim(p_issuer), btrim(p_subject)) r
    LIMIT 1;
  END IF;

  IF v_user_id IS NULL OR v_provider_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS403', 'external identity is not linked to a user for this scope');
  END IF;

  SELECT o.session_token, o.session_id, o.expires_at_utc
  INTO v_open
  FROM portal.sp_session_open(
    v_user_id,
    p_scope_id,
    v_provider_id,
    COALESCE(NULLIF(btrim(p_auth_subject_snapshot), ''), btrim(p_subject))
  ) o
  LIMIT 1;

  RETURN QUERY
  SELECT v_open.session_token, v_open.session_id, v_open.expires_at_utc, v_user_id, v_provider_id;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_list_scope_identity_providers(p_session_token text)
RETURNS TABLE (
  provider_id int,
  provider_name text,
  issuer text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  RETURN QUERY
  SELECT ip."ProviderID", ip."Name"::text, ip."Issuer"::text
  FROM "RBAC"."ScopeIdentityProviders" sip
  INNER JOIN "RBAC"."IdentityProviders" ip ON ip."ProviderID" = sip."ProviderID"
  WHERE sip."ScopeID" = v_ctx.active_scope_id
    AND sip."Active" = true
    AND ip."Active" = true
  ORDER BY ip."Name";
END;
$$;

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
SET search_path = portal, "RBAC", pg_temp
AS $$
DECLARE
  v_ctx record;
  v_provider_count int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;

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
    SELECT sp.provider_id, sp.provider_name
    FROM scope_providers sp
    ORDER BY sp.provider_name
    LIMIT 1
  )
  SELECT
    u."ID"::int,
    u."FullName"::text,
    u.email::text,
    u."Active"::int,
    (
      SELECT COUNT(*)::int
      FROM "RBAC"."UserRoleGrants" g
      WHERE g."UserID" = u."ID"
        AND g."ScopeID" = v_ctx.active_scope_id
        AND g."Active" = true
        AND g."RevokedAtUtc" IS NULL
    ) AS scoped_role_count,
    (
      SELECT string_agg(
        format('%s (%s)', r."Name", COALESCE(s."Name", 'Scope')),
        ', '
        ORDER BY r."Name"
      )
      FROM "RBAC"."UserRoleGrants" g
      INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
      LEFT JOIN "RBAC"."Scopes" s ON s."ScopeID" = g."ScopeID"
      WHERE g."UserID" = u."ID"
        AND g."ScopeID" = v_ctx.active_scope_id
        AND g."Active" = true
        AND g."RevokedAtUtc" IS NULL
    )::text AS active_roles_summary,
    CASE
      WHEN v_provider_count = 0 THEN 'no_provider'
      WHEN EXISTS (
        SELECT 1
        FROM "RBAC"."ExternalIdentities" ei
        INNER JOIN scope_providers sp ON sp."ProviderID" = ei."ProviderID"
        WHERE ei."UserID" = u."ID" AND ei."Active" = true
      ) THEN 'linked'
      WHEN u."Active" = 1 AND NULLIF(btrim(u.email), '') IS NOT NULL THEN 'awaiting_first_sign_in'
      ELSE 'inactive'
    END::text AS sign_in_status,
    (SELECT pp.provider_name FROM primary_provider pp)::text AS identity_provider_name
  FROM "RBAC"."Users" u
  ORDER BY u."ID";
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_create_invitation_scoped(
  p_session_token text,
  p_email text,
  p_default_role_id integer,
  p_expected_provider_id integer DEFAULT NULL
)
RETURNS TABLE (invitation_id bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", "Onboarding", "Contract", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_email text;
  v_provider_id int;
  v_id bigint;
  v_role_ok boolean;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;

  v_email := portal.fn_validate_invitation_email(p_email);

  IF p_default_role_id IS NULL OR p_default_role_id <= 0 THEN
    PERFORM portal.fn_semantic_raise('GS400', 'default_role_id is required');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM "RBAC"."Roles" r WHERE r."ID" = p_default_role_id) THEN
    PERFORM portal.fn_semantic_raise('GS404', 'role not found');
  END IF;

  SELECT a.is_allowed INTO v_role_ok
  FROM "Contract".spcontractvalidaterolegrant(v_ctx.active_scope_id, p_default_role_id, now() AT TIME ZONE 'utc') a
  LIMIT 1;

  IF COALESCE(v_role_ok, false) = false THEN
    PERFORM portal.fn_semantic_raise('GS400', 'role is not allowed for this scope contract');
  END IF;

  v_provider_id := portal.fn_resolve_scope_identity_provider(v_ctx.active_scope_id, p_expected_provider_id);

  IF EXISTS (
    SELECT 1
    FROM "Onboarding"."Invitations" i
    WHERE i."ScopeID" = v_ctx.active_scope_id
      AND i."Email" = v_email
      AND i."Status" = 'PENDING'
      AND i."ExpiresAtUtc" >= (now() AT TIME ZONE 'utc')
  ) THEN
    PERFORM portal.fn_semantic_raise('GS409', 'pending invitation already exists for this email');
  END IF;

  SELECT i.invitation_id INTO v_id
  FROM portal.sp_create_invitation(
    v_ctx.active_scope_id,
    v_email,
    v_provider_id,
    (now() AT TIME ZONE 'utc') + interval '14 days',
    NULL,
    p_default_role_id,
    'SCOPED',
    NULL
  ) i;

  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'user.invite',
    jsonb_build_object(
      'email', v_email,
      'invitation_id', v_id,
      'provider_id', v_provider_id,
      'default_role_id', p_default_role_id
    )
  );
  RETURN QUERY SELECT v_id;
END;
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
  v_org_id int;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;
  SELECT portal.sp_upsert_user(p_email, p_full_name, p_active) INTO v_uid;

  SELECT s."OrganizationID" INTO v_org_id
  FROM "RBAC"."Scopes" s
  WHERE s."ScopeID" = v_ctx.active_scope_id
  LIMIT 1;

  IF v_org_id IS NOT NULL THEN
    PERFORM portal.sp_organization_add_member(v_org_id, v_uid);
  END IF;

  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id, v_ctx.user_id, v_ctx.active_scope_id, 'user.upsert',
    jsonb_build_object('email', p_email, 'user_id', v_uid)
  );
  RETURN QUERY SELECT v_uid;
END;
$$;

DROP FUNCTION IF EXISTS portal.sp_session_list_user_role_grants_scoped(text, integer);

CREATE OR REPLACE FUNCTION portal.sp_session_list_user_role_grants_scoped(
  p_session_token text,
  p_target_user_id integer
)
RETURNS TABLE (
  grant_id bigint,
  user_id int,
  role_id int,
  role_name text,
  grant_type text,
  scope_id int,
  scope_name text
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
  IF p_target_user_id IS NULL OR p_target_user_id <= 0 THEN
    PERFORM portal.fn_semantic_raise('GS400', 'target user is required');
  END IF;
  RETURN QUERY
  SELECT
    g."ID"::bigint,
    g."UserID",
    g."RoleID",
    r."Name"::text,
    g."GrantType"::text,
    g."ScopeID",
    s."Name"::text
  FROM "RBAC"."UserRoleGrants" g
  INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
  LEFT JOIN "RBAC"."Scopes" s ON s."ScopeID" = g."ScopeID"
  WHERE g."UserID" = p_target_user_id
    AND g."ScopeID" = v_ctx.active_scope_id
    AND g."Active" = true
    AND g."RevokedAtUtc" IS NULL
  ORDER BY r."Name", g."ID";
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_revoke_user_role_grant(
  p_session_token text,
  p_grant_id bigint
)
RETURNS TABLE (revoked boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", public, pg_temp
AS $$
DECLARE
  v_ctx record;
  v_grant record;
  v_org_admin_id int;
  v_peer_admin_count int;
  v_rows bigint;
BEGIN
  SELECT * INTO v_ctx FROM portal.fn_session_security_admin_require(p_session_token, '/app/admin/users') LIMIT 1;

  IF p_grant_id IS NULL OR p_grant_id <= 0 THEN
    PERFORM portal.fn_semantic_raise('GS400', 'grant_id is required');
  END IF;

  SELECT g."ID", g."UserID", g."RoleID", g."ScopeID", g."GrantType", r."Name" AS role_name
  INTO v_grant
  FROM "RBAC"."UserRoleGrants" g
  INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
  WHERE g."ID" = p_grant_id
    AND g."Active" = true
    AND g."RevokedAtUtc" IS NULL
  LIMIT 1;

  IF v_grant."ID" IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS404', 'role grant not found');
  END IF;

  IF v_grant."ScopeID" IS DISTINCT FROM v_ctx.active_scope_id THEN
    PERFORM portal.fn_semantic_raise('GS403', 'role grant is outside the active scope');
  END IF;

  SELECT r."ID" INTO v_org_admin_id FROM "RBAC"."Roles" r WHERE r."Name" = 'organization_admin' LIMIT 1;

  IF v_org_admin_id IS NOT NULL
     AND v_grant."UserID" = v_ctx.user_id
     AND v_grant."RoleID" = v_org_admin_id THEN
    SELECT COUNT(*)::int INTO v_peer_admin_count
    FROM "RBAC"."UserRoleGrants" g
    WHERE g."RoleID" = v_org_admin_id
      AND g."ScopeID" = v_ctx.active_scope_id
      AND g."Active" = true
      AND g."RevokedAtUtc" IS NULL;
    IF v_peer_admin_count <= 1 THEN
      PERFORM portal.fn_semantic_raise('GS403', 'cannot revoke your last organization_admin grant in this scope');
    END IF;
  END IF;

  UPDATE "RBAC"."UserRoleGrants"
  SET "Active" = false,
      "RevokedAtUtc" = now() AT TIME ZONE 'utc'
  WHERE "ID" = p_grant_id
    AND "Active" = true
    AND "RevokedAtUtc" IS NULL;

  GET DIAGNOSTICS v_rows = ROW_COUNT;
  IF v_rows < 1 THEN
    PERFORM portal.fn_semantic_raise('GS404', 'role grant not found');
  END IF;

  PERFORM portal.fn_session_security_admin_audit(
    v_ctx.session_id,
    v_ctx.user_id,
    v_ctx.active_scope_id,
    'user.revoke_role_grant',
    jsonb_build_object(
      'grant_id', p_grant_id,
      'target_user_id', v_grant."UserID",
      'role_id', v_grant."RoleID",
      'role_name', v_grant.role_name
    )
  );

  RETURN QUERY SELECT true;
END;
$$;

