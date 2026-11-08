/*
  Interactive operator login: resolve issuer+subject within a scope, then mint portal session.
  No implicit account creation or email-only matching — requires pre-linked ExternalIdentities.
*/

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
SET search_path = portal, "RBAC", cfg, pg_temp
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
