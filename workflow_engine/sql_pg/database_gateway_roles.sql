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

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA portal TO goliath_portal;
GRANT USAGE ON SCHEMA cfg TO goliath_portal;

REVOKE ALL ON ALL TABLES IN SCHEMA portal FROM goliath_portal;
REVOKE ALL ON ALL TABLES IN SCHEMA cfg FROM goliath_portal;
REVOKE ALL ON ALL TABLES IN SCHEMA wf FROM goliath_portal;
REVOKE ALL ON ALL TABLES IN SCHEMA "RBAC" FROM goliath_portal;
REVOKE ALL ON ALL TABLES IN SCHEMA "Meta" FROM goliath_portal;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA portal TO goliath_portal;
ALTER DEFAULT PRIVILEGES IN SCHEMA portal GRANT EXECUTE ON FUNCTIONS TO goliath_portal;

REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA wf FROM goliath_portal;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA portal FROM goliath_gateway;

GRANT USAGE ON SCHEMA wf TO goliath_gateway;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA wf TO goliath_gateway;
ALTER DEFAULT PRIVILEGES IN SCHEMA wf GRANT EXECUTE ON FUNCTIONS TO goliath_gateway;
