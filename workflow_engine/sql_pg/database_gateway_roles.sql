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
