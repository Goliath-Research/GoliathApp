/*
  Worker gateway sessions (P3): bearer session + identity token + bound IP.
  Replaces plaintext worker_token on wf.sp_worker_* entry points.
*/

CREATE OR REPLACE FUNCTION wf.fn_worker_session_ttl_seconds()
RETURNS int
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = wf, cfg, pg_temp
AS $$
  SELECT cfg.fn_portal_auth_int('worker_heartbeat_seconds', 60)
       * cfg.fn_portal_auth_int('worker_session_miss_factor', 3);
$$;

CREATE OR REPLACE FUNCTION wf.wf_ensure_worker_rbac_user(p_worker_id bigint)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, "RBAC", pg_temp
AS $$
DECLARE
  v_uid int;
  v_email text;
  v_name text;
  v_role_id int;
BEGIN
  SELECT w.rbac_user_id, w.external_worker_key
  INTO v_uid, v_name
  FROM wf.worker w
  WHERE w.id = p_worker_id;

  IF v_uid IS NOT NULL THEN
    RETURN v_uid;
  END IF;

  v_email := format('worker-%s@workers.goliath.internal', p_worker_id);
  INSERT INTO "RBAC"."Users" ("FullName", email, "Active", username)
  VALUES (coalesce(v_name, v_email), v_email, 1, v_email)
  RETURNING "ID" INTO v_uid;

  UPDATE wf.worker SET rbac_user_id = v_uid WHERE id = p_worker_id;

  SELECT r."ID" INTO v_role_id FROM "RBAC"."Roles" r WHERE r."Name" = 'worker' LIMIT 1;
  IF v_role_id IS NULL THEN
    INSERT INTO "RBAC"."Roles" ("Name", "BypassScope") VALUES ('worker', false)
    RETURNING "ID" INTO v_role_id;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM "RBAC"."UserRoleGrants" g
    WHERE g."UserID" = v_uid AND g."RoleID" = v_role_id AND g."GrantType" = 'DIRECT' AND g."Active"
  ) THEN
    INSERT INTO "RBAC"."UserRoleGrants" (
      "UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc"
    )
    VALUES (v_uid, v_role_id, 'DIRECT', NULL, true, now() AT TIME ZONE 'utc');
  END IF;

  RETURN v_uid;
END;
$$;

CREATE OR REPLACE PROCEDURE wf.wf_worker_expire_stale_sessions()
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, "RBAC", cfg, pg_temp
AS $$
DECLARE
  v_now timestamptz := now() AT TIME ZONE 'utc';
  v_ttl int := wf.fn_worker_session_ttl_seconds();
  rec record;
BEGIN
  FOR rec IN
    SELECT st."SessionID", s."UserID", w.id AS worker_id
    FROM "RBAC"."SessionTokens" st
    INNER JOIN "RBAC"."Sessions" s ON s."ID" = st."SessionID"
    INNER JOIN wf.worker w ON w.rbac_user_id = s."UserID"
    WHERE st."RevokedAtUtc" IS NULL
      AND st."LastRefreshedAtUtc" + make_interval(secs => v_ttl) < v_now
  LOOP
    UPDATE "RBAC"."SessionTokens"
    SET "RevokedAtUtc" = v_now
    WHERE "SessionID" = rec."SessionID" AND "RevokedAtUtc" IS NULL;

    IF NOT EXISTS (
      SELECT 1
      FROM "RBAC"."SessionTokens" st2
      INNER JOIN "RBAC"."Sessions" s2 ON s2."ID" = st2."SessionID"
      WHERE s2."UserID" = rec."UserID"
        AND st2."RevokedAtUtc" IS NULL
        AND st2."LastRefreshedAtUtc" + make_interval(secs => v_ttl) >= v_now
    ) THEN
      UPDATE wf.worker
      SET status = 'FAILED', updated_at_utc = v_now
      WHERE id = rec.worker_id AND status IN ('REGISTERED', 'READY');

      PERFORM * FROM wf.sp_reclaim_expired_leases(NULL::bigint, 60, true, rec.worker_id);
    END IF;
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION wf.wf_worker_session_touch(p_session_token text)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, "RBAC", cfg, pg_temp
AS $$
DECLARE
  v_hash bytea;
  v_now timestamptz := now() AT TIME ZONE 'utc';
  v_ttl int := wf.fn_worker_session_ttl_seconds();
  v_n int;
BEGIN
  IF NULLIF(btrim(p_session_token), '') IS NULL THEN
    RETURN false;
  END IF;
  v_hash := wf.wf_sha256_text(btrim(p_session_token));
  UPDATE "RBAC"."SessionTokens" st
  SET "LastRefreshedAtUtc" = v_now,
      "ExpiresAtUtc" = v_now + make_interval(secs => v_ttl)
  WHERE st."TokenHash" = v_hash
    AND st."RevokedAtUtc" IS NULL;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n > 0;
END;
$$;

CREATE OR REPLACE PROCEDURE wf.wf_worker_authenticate(
  IN p_worker_id bigint,
  IN p_session_token text,
  IN p_identity_token text,
  IN p_client_ip text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, "RBAC", cfg, pg_temp
AS $$
DECLARE
  v_hash_session bytea;
  v_hash_identity bytea;
  v_now timestamptz := now() AT TIME ZONE 'utc';
  v_ttl int := wf.fn_worker_session_ttl_seconds();
  v_uid int;
  v_sid int;
  v_last timestamptz;
  v_revoked timestamptz;
  v_bound_ip text;
  v_locked timestamptz;
  v_status text;
BEGIN
  CALL wf.wf_worker_expire_stale_sessions();

  IF p_worker_id IS NULL THEN
    RAISE EXCEPTION 'worker_id is required' USING ERRCODE = '50002';
  END IF;
  IF NULLIF(btrim(p_session_token), '') IS NULL THEN
    RAISE EXCEPTION 'session token is required' USING ERRCODE = '50002';
  END IF;
  IF NULLIF(btrim(p_identity_token), '') IS NULL THEN
    RAISE EXCEPTION 'identity token is required' USING ERRCODE = '50002';
  END IF;
  IF NULLIF(btrim(p_client_ip), '') IS NULL THEN
    RAISE EXCEPTION 'client_ip is required' USING ERRCODE = '50002';
  END IF;

  SELECT w.status, w.rbac_user_id
  INTO v_status, v_uid
  FROM wf.worker w
  INNER JOIN wf.cluster c ON c.id = w.cluster_id
  WHERE w.id = p_worker_id
    AND c.status = 'ACTIVE';

  IF v_status IS NULL THEN
    RAISE EXCEPTION 'Invalid or unauthorized worker credentials' USING ERRCODE = '50003';
  END IF;
  IF v_status = 'DISABLED' THEN
    RAISE EXCEPTION 'Worker is disabled' USING ERRCODE = '50003';
  END IF;
  IF v_status = 'FAILED' THEN
    RAISE EXCEPTION 'Worker session expired; open a new session' USING ERRCODE = '50003';
  END IF;

  v_hash_session := wf.wf_sha256_text(btrim(p_session_token));
  v_hash_identity := wf.wf_sha256_text(btrim(p_identity_token));

  SELECT wt.bound_client_ip, wt.locked_until_utc
  INTO v_bound_ip, v_locked
  FROM wf.worker_token wt
  WHERE wt.worker_id = p_worker_id
    AND wt.token_hash = v_hash_identity
    AND wt.status = 'ACTIVE';

  IF v_bound_ip IS NULL THEN
    RAISE EXCEPTION 'Invalid or unauthorized worker credentials' USING ERRCODE = '50003';
  END IF;
  IF v_locked IS NOT NULL AND v_locked > v_now THEN
    RAISE EXCEPTION 'Worker identity locked; re-enroll required' USING ERRCODE = '50003';
  END IF;

  IF NULLIF(btrim(v_bound_ip), '') IS NULL THEN
    RAISE EXCEPTION 'Worker identity requires re-enrollment (no bound IP)' USING ERRCODE = '50003';
  END IF;

  IF btrim(p_client_ip) <> btrim(v_bound_ip)
     AND btrim(p_client_ip) <> split_part(btrim(v_bound_ip), '/', 1) THEN
    RAISE EXCEPTION 'client IP does not match enrolled worker IP' USING ERRCODE = '50003';
  END IF;

  SELECT st."SessionID", st."LastRefreshedAtUtc", st."RevokedAtUtc"
  INTO v_sid, v_last, v_revoked
  FROM "RBAC"."SessionTokens" st
  INNER JOIN "RBAC"."Sessions" s ON s."ID" = st."SessionID"
  WHERE st."TokenHash" = v_hash_session
    AND s."UserID" = v_uid;

  IF v_sid IS NULL OR v_revoked IS NOT NULL THEN
    RAISE EXCEPTION 'Invalid or expired worker session' USING ERRCODE = '50003';
  END IF;
  IF v_last + make_interval(secs => v_ttl) < v_now THEN
    RAISE EXCEPTION 'Invalid or expired worker session' USING ERRCODE = '50003';
  END IF;

  PERFORM wf.wf_worker_session_touch(p_session_token);

  UPDATE wf.worker
  SET last_seen_at_utc = v_now,
      status = CASE WHEN status = 'READY' THEN 'REGISTERED' ELSE status END
  WHERE id = p_worker_id;
END;
$$;

CREATE OR REPLACE FUNCTION wf.sp_worker_open_session(
  p_identity_token text,
  p_client_ip text
)
RETURNS TABLE (session_token text, worker_id bigint, expires_at_utc timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, "RBAC", cfg, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_hash bytea;
  v_worker_id bigint;
  v_bound_ip text;
  v_locked timestamptz;
  v_status text;
  v_uid int;
  v_session_id int;
  v_token text;
  v_now timestamptz := now() AT TIME ZONE 'utc';
  v_ttl int := wf.fn_worker_session_ttl_seconds();
  v_max_fail int := cfg.fn_portal_auth_int('worker_session_max_failed_attempts', 3);
BEGIN
  IF NULLIF(btrim(p_identity_token), '') IS NULL THEN
    RAISE EXCEPTION 'identity token is required' USING ERRCODE = '50002';
  END IF;
  IF NULLIF(btrim(p_client_ip), '') IS NULL THEN
    RAISE EXCEPTION 'client_ip is required' USING ERRCODE = '50002';
  END IF;

  v_hash := wf.wf_sha256_text(btrim(p_identity_token));

  SELECT wt.worker_id, wt.bound_client_ip, wt.locked_until_utc, w.status
  INTO v_worker_id, v_bound_ip, v_locked, v_status
  FROM wf.worker_token wt
  INNER JOIN wf.worker w ON w.id = wt.worker_id
  INNER JOIN wf.cluster c ON c.id = w.cluster_id
  WHERE wt.token_hash = v_hash
    AND wt.status = 'ACTIVE'
    AND c.status = 'ACTIVE';

  IF v_worker_id IS NULL THEN
    RAISE EXCEPTION 'Invalid or unauthorized worker credentials' USING ERRCODE = '50003';
  END IF;
  IF v_status = 'DISABLED' THEN
    RAISE EXCEPTION 'Worker is disabled' USING ERRCODE = '50003';
  END IF;

  IF v_locked IS NOT NULL AND v_locked > v_now THEN
    RAISE EXCEPTION 'Worker identity locked; re-enroll required' USING ERRCODE = '50003';
  END IF;

  IF NULLIF(btrim(v_bound_ip), '') IS NULL THEN
    RAISE EXCEPTION 'Worker identity requires re-enrollment (no bound IP)' USING ERRCODE = '50003';
  END IF;

  IF btrim(p_client_ip) <> btrim(v_bound_ip)
     AND btrim(p_client_ip) <> split_part(btrim(v_bound_ip), '/', 1) THEN
    UPDATE wf.worker_token
    SET failed_session_attempts = failed_session_attempts + 1,
        locked_until_utc = CASE
          WHEN failed_session_attempts + 1 >= v_max_fail THEN 'infinity'::timestamptz
          ELSE locked_until_utc
        END
    WHERE worker_id = v_worker_id;
    RETURN;
  END IF;

  v_uid := wf.wf_ensure_worker_rbac_user(v_worker_id);

  UPDATE "RBAC"."SessionTokens" st
  SET "RevokedAtUtc" = v_now
  FROM "RBAC"."Sessions" s
  WHERE st."SessionID" = s."ID"
    AND s."UserID" = v_uid
    AND st."RevokedAtUtc" IS NULL;

  v_token := replace(
    gen_random_uuid()::text || gen_random_uuid()::text || gen_random_uuid()::text || gen_random_uuid()::text,
    '-',
    ''
  );

  INSERT INTO "RBAC"."Sessions" ("Name", "UserID", "Created", "AuthenticatedAtUtc")
  VALUES ('worker-gateway', v_uid, v_now, v_now)
  RETURNING "ID" INTO v_session_id;

  INSERT INTO "RBAC"."SessionTokens" (
    "SessionID", "TokenHash", "ExpiresAtUtc", "LastRefreshedAtUtc", "CreatedAtUtc"
  )
  VALUES (
    v_session_id,
    wf.wf_sha256_text(v_token),
    v_now + make_interval(secs => v_ttl),
    v_now,
    v_now
  );

  UPDATE wf.worker_token
  SET failed_session_attempts = 0,
      locked_until_utc = NULL
  WHERE worker_id = v_worker_id;

  UPDATE wf.worker
  SET status = CASE WHEN status = 'FAILED' THEN 'READY' ELSE status END,
      updated_at_utc = v_now
  WHERE id = v_worker_id;

  RETURN QUERY SELECT v_token, v_worker_id, v_now + make_interval(secs => v_ttl);
END;
$$;
