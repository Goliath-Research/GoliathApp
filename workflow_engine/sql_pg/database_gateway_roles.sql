/*
  Least-privilege DB roles for portal direct connect vs worker gateway.
  Run as superuser / dba after portal and wf APIs are deployed.
*/

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'goliath_portal') THEN
    CREATE ROLE goliath_portal LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'goliath_gateway') THEN
    CREATE ROLE goliath_gateway LOGIN;
  END IF;
END $$;

GRANT USAGE ON SCHEMA portal TO goliath_portal;

REVOKE ALL ON ALL TABLES IN SCHEMA portal FROM goliath_portal;
REVOKE ALL ON ALL TABLES IN SCHEMA cfg FROM goliath_portal;
REVOKE ALL ON ALL TABLES IN SCHEMA wf FROM goliath_portal;
REVOKE ALL ON ALL TABLES IN SCHEMA "RBAC" FROM goliath_portal;
REVOKE ALL ON ALL TABLES IN SCHEMA "Meta" FROM goliath_portal;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA portal TO goliath_portal;
ALTER DEFAULT PRIVILEGES IN SCHEMA portal GRANT EXECUTE ON FUNCTIONS TO goliath_portal;

REVOKE USAGE ON SCHEMA cfg FROM goliath_portal;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA cfg FROM goliath_portal;
REVOKE EXECUTE ON FUNCTION cfg.cfg_repo_get_credential_secret(text, text) FROM PUBLIC;

REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA wf FROM goliath_portal;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA portal FROM goliath_gateway;

GRANT USAGE ON SCHEMA wf TO goliath_gateway;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA wf TO goliath_gateway;
GRANT EXECUTE ON PROCEDURE wf.wf_worker_authenticate(bigint, text, text, text) TO goliath_gateway;
GRANT EXECUTE ON PROCEDURE wf.wf_worker_expire_stale_sessions() TO goliath_gateway;
GRANT EXECUTE ON PROCEDURE wf.sp_worker_fail_task(
  bigint, bigint, text, text, text, int, text
) TO goliath_gateway;
ALTER DEFAULT PRIVILEGES IN SCHEMA wf GRANT EXECUTE ON FUNCTIONS TO goliath_gateway;

-- Semantic read path: goliath_portal calls sp_run_semantic_request only (not filter/compiler internals).
DO $$
DECLARE
  v_sig regprocedure;
BEGIN
  FOR v_sig IN
    SELECT p.oid::regprocedure
    FROM pg_proc p
    INNER JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'portal'
      AND p.prokind = 'f'
      AND p.proname = ANY (
        ARRAY[
          'fn_semantic_compile_filter',
          'fn_semantic_core_filter_organizations',
          'fn_semantic_core_list_organizations',
          'fn_semantic_assert_safe_compiled_where',
          'fn_semantic_validate_params',
          'fn_semantic_property_json_type',
          'fn_semantic_property_allows_null',
          'fn_semantic_user_organization_ids',
          'fn_semantic_raise'
        ]
      )
  LOOP
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, goliath_portal', v_sig);
  END LOOP;

  FOR v_sig IN
    SELECT p.oid::regprocedure
    FROM pg_proc p
    INNER JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'portal'
      AND p.prokind = 'p'
      AND p.proname LIKE 'sp_semantic_register%'
  LOOP
    EXECUTE format('REVOKE EXECUTE ON PROCEDURE %s FROM PUBLIC, goliath_portal', v_sig);
  END LOOP;
END $$;
