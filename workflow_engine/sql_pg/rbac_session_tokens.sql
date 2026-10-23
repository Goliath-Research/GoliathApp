/*
  Portal and worker bearer sessions (P3 semantic auth).
  Plaintext tokens are never stored — only SHA-256 hashes of 256-bit random tokens.
*/

CREATE SCHEMA IF NOT EXISTS cfg;

ALTER TABLE wf.worker DROP CONSTRAINT IF EXISTS worker_status_check;
ALTER TABLE wf.worker
  ADD CONSTRAINT worker_status_check
  CHECK (status IN ('REGISTERED', 'DISABLED', 'FAILED', 'READY'));

ALTER TABLE wf.worker
  ADD COLUMN IF NOT EXISTS rbac_user_id integer NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'FK_worker_rbac_user'
  ) THEN
    ALTER TABLE wf.worker
      ADD CONSTRAINT "FK_worker_rbac_user"
      FOREIGN KEY (rbac_user_id) REFERENCES "RBAC"."Users" ("ID");
  END IF;
END $$;

ALTER TABLE wf.worker_token
  ADD COLUMN IF NOT EXISTS bound_client_ip text NULL;

ALTER TABLE wf.worker_token
  ADD COLUMN IF NOT EXISTS failed_session_attempts integer NOT NULL DEFAULT 0;

ALTER TABLE wf.worker_token
  ADD COLUMN IF NOT EXISTS locked_until_utc timestamptz NULL;

CREATE TABLE IF NOT EXISTS "RBAC"."SessionTokens" (
  "SessionID" integer NOT NULL REFERENCES "RBAC"."Sessions" ("ID") ON DELETE CASCADE,
  "TokenHash" bytea NOT NULL,
  "ExpiresAtUtc" timestamptz NOT NULL,
  "RevokedAtUtc" timestamptz NULL,
  "LastRefreshedAtUtc" timestamptz NOT NULL,
  "CreatedAtUtc" timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT "PK_RBAC_SessionTokens" PRIMARY KEY ("SessionID")
);

CREATE INDEX IF NOT EXISTS "IX_SessionTokens_ExpiresAtUtc"
  ON "RBAC"."SessionTokens" ("ExpiresAtUtc")
  WHERE "RevokedAtUtc" IS NULL;

CREATE TABLE IF NOT EXISTS cfg.portal_auth_defaults (
  key text PRIMARY KEY,
  value_json jsonb NOT NULL
);

INSERT INTO cfg.portal_auth_defaults (key, value_json)
VALUES
  ('portal_session_idle_seconds', '1800'::jsonb),
  ('portal_session_absolute_seconds', '43200'::jsonb),
  ('worker_heartbeat_seconds', '60'::jsonb),
  ('worker_session_miss_factor', '3'::jsonb),
  ('worker_session_max_failed_attempts', '3'::jsonb)
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION cfg.fn_portal_auth_int(p_key text, p_default int)
RETURNS int
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(
    (SELECT (d.value_json #>> '{}')::int FROM cfg.portal_auth_defaults d WHERE d.key = p_key),
    p_default
  );
$$;

CREATE OR REPLACE FUNCTION cfg.fn_portal_auth_int(p_key text)
RETURNS int
LANGUAGE sql
STABLE
AS $$
  SELECT cfg.fn_portal_auth_int(p_key, 0);
$$;
