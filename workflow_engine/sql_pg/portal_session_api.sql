/*
  Portal user sessions and optional auth policy hooks (P3).
  portal.sp_session_* are SECURITY DEFINER with a fixed search_path.
*/

CREATE TABLE IF NOT EXISTS portal.auth_policy (
  namespace text PRIMARY KEY,
  policy_function text NOT NULL,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE OR REPLACE FUNCTION portal.fn_session_policy_idle_seconds()
RETURNS int
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
  SELECT cfg.fn_portal_auth_int('portal_session_idle_seconds', 1800);
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_policy_absolute_seconds()
RETURNS int
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, cfg, pg_temp
AS $$
  SELECT cfg.fn_portal_auth_int('portal_session_absolute_seconds', 43200);
$$;

CREATE OR REPLACE FUNCTION portal.sp_auth_register_policy(
  p_namespace text,
  p_function text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
BEGIN
  IF NULLIF(btrim(p_namespace), '') IS NULL THEN
    RAISE EXCEPTION 'namespace is required' USING ERRCODE = 'P0001';
  END IF;
  IF NULLIF(btrim(p_function), '') IS NULL THEN
    RAISE EXCEPTION 'function is required' USING ERRCODE = 'P0001';
  END IF;
  INSERT INTO portal.auth_policy (namespace, policy_function)
  VALUES (btrim(p_namespace), btrim(p_function))
  ON CONFLICT (namespace) DO UPDATE
    SET policy_function = EXCLUDED.policy_function,
        created_at_utc = now() AT TIME ZONE 'utc';
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

  RETURN QUERY
  SELECT
    v_token,
    v_session_id,
    v_now + make_interval(secs => LEAST(v_idle, v_abs));
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_session_resolve(p_session_token text)
RETURNS TABLE (
  session_id int,
  user_id int,
  email text,
  full_name text,
  active_scope_id int,
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

  IF to_regclass('portal."Organizations"') IS NOT NULL THEN
    EXECUTE $q$
      SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'organization_id', o."ID",
        'name', o."Name"
      ) ORDER BY o."Name"), '[]'::jsonb)
      FROM portal."Organizations" o
    $q$ INTO v_orgs;
  END IF;

  RETURN QUERY
  SELECT
    v_sid,
    v_uid,
    u.email::text,
    u."FullName"::text,
    v_scope,
    v_orgs,
    v_exp,
    false
  FROM "RBAC"."Users" u
  WHERE u."ID" = v_uid;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_revoke(p_session_token text)
RETURNS TABLE (revoked boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", cfg, pg_temp
AS $$
DECLARE
  v_hash bytea;
  v_n int;
BEGIN
  IF NULLIF(btrim(p_session_token), '') IS NULL THEN
    RETURN QUERY SELECT false;
    RETURN;
  END IF;
  v_hash := wf.wf_sha256_text(btrim(p_session_token));
  UPDATE "RBAC"."SessionTokens" st
  SET "RevokedAtUtc" = now() AT TIME ZONE 'utc'
  WHERE st."TokenHash" = v_hash AND st."RevokedAtUtc" IS NULL;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN QUERY SELECT v_n > 0;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_session_touch(p_session_token text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, "RBAC", cfg, pg_temp
AS $$
DECLARE
  v_hash bytea;
  v_now timestamptz := now() AT TIME ZONE 'utc';
  v_idle int := portal.fn_session_policy_idle_seconds();
  v_n int;
BEGIN
  v_hash := wf.wf_sha256_text(btrim(p_session_token));
  UPDATE "RBAC"."SessionTokens" st
  SET "LastRefreshedAtUtc" = v_now,
      "ExpiresAtUtc" = v_now + make_interval(secs => v_idle)
  WHERE st."TokenHash" = v_hash
    AND st."RevokedAtUtc" IS NULL;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n > 0;
END;
$$;
