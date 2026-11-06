/*
  Server-side authorization for event ingest (workers + portal/API keys).
  Prerequisites: 00_schema.sql (wf.worker), wf_event_plane.sql, wf_worker_session_api.sql, wf_worker_ingest_event.sql
*/

-- Binding for adapter workers: canonical event source + org + optional device + event type allowlists.
ALTER TABLE wf.worker
  ADD COLUMN IF NOT EXISTS event_ingest_binding jsonb NULL;

COMMENT ON COLUMN wf.worker.event_ingest_binding IS
  'When set, worker may POST /v1/events only when source/org/device/event_type match this JSON '
  '(keys: org_key text, source text required exact match, device_id optional, event_types jsonb array of '
  'exact names or "*" for any). NULL denies worker event ingest.';

CREATE TABLE IF NOT EXISTS wf.event_ingest_api_key (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  key_hash bytea NOT NULL UNIQUE,
  label text NOT NULL DEFAULT '',
  allowed_org_keys jsonb NOT NULL DEFAULT '["*"]'::jsonb,
  allowed_sources jsonb NOT NULL DEFAULT '["*"]'::jsonb,
  allowed_event_types jsonb NOT NULL DEFAULT '["*"]'::jsonb,
  status varchar(32) NOT NULL DEFAULT 'ACTIVE',
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CHECK (status IN ('ACTIVE', 'REVOKED'))
);

CREATE INDEX IF NOT EXISTS ix_event_ingest_api_key_status ON wf.event_ingest_api_key(status);

CREATE OR REPLACE FUNCTION wf.wf_jsonb_array_contains_star(p_arr jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT p_arr IS NOT NULL AND p_arr @> '["*"]'::jsonb;
$$;

CREATE OR REPLACE FUNCTION wf.wf_event_type_allowed(p_allowed jsonb, p_event_type text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT
    wf.wf_jsonb_array_contains_star(p_allowed)
    OR EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(coalesce(p_allowed, '[]'::jsonb)) AS t(etype)
      WHERE t.etype = p_event_type
    );
$$;

CREATE OR REPLACE FUNCTION wf.wf_event_source_allowed(p_allowed jsonb, p_source text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT
    wf.wf_jsonb_array_contains_star(p_allowed)
    OR EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(coalesce(p_allowed, '[]'::jsonb)) AS t(pref)
      WHERE p_source = t.pref OR p_source LIKE (t.pref || '%')
    );
$$;

CREATE OR REPLACE FUNCTION wf.wf_org_key_allowed(p_allowed jsonb, p_org text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT
    wf.wf_jsonb_array_contains_star(p_allowed)
    OR EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(coalesce(p_allowed, '[]'::jsonb)) AS t(okey)
      WHERE t.okey = p_org
    );
$$;

CREATE OR REPLACE FUNCTION wf.wf_worker_event_binding_valid(
  p_binding jsonb,
  p_event_type text,
  p_source text,
  p_payload jsonb
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_src text := btrim(p_source);
  v_org_payload text;
  v_dev_payload text;
  v_bound_src text;
  v_bound_org text;
  v_bound_dev text;
  v_types jsonb;
BEGIN
  IF p_binding IS NULL OR p_binding = '{}'::jsonb THEN
    RETURN false;
  END IF;
  v_bound_src := btrim(coalesce(p_binding->>'source', ''));
  IF v_bound_src IS NULL OR v_bound_src = '' THEN
    RETURN false;
  END IF;
  IF v_src <> v_bound_src THEN
    RETURN false;
  END IF;

  v_bound_org := btrim(coalesce(p_binding->>'org_key', ''));
  v_org_payload := btrim(coalesce(p_payload->>'organization_key', ''));
  IF v_bound_org IS NOT NULL AND v_bound_org <> '' AND v_bound_org <> '*' THEN
    IF v_org_payload IS NULL OR v_org_payload = '' OR v_org_payload <> v_bound_org THEN
      RETURN false;
    END IF;
  END IF;

  v_bound_dev := NULLIF(btrim(coalesce(p_binding->>'device_id', '')), '');
  IF v_bound_dev IS NOT NULL THEN
    v_dev_payload := btrim(coalesce(p_payload->>'device_key', ''));
    IF v_dev_payload IS NULL OR v_dev_payload = '' OR v_dev_payload <> v_bound_dev THEN
      RETURN false;
    END IF;
  END IF;

  v_types := p_binding->'event_types';
  IF v_types IS NULL THEN
    v_types := '["*"]'::jsonb;
  END IF;
  IF NOT wf.wf_event_type_allowed(v_types, p_event_type) THEN
    RETURN false;
  END IF;

  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION wf.wf_authorize_worker_event_ingest(
  p_worker_id bigint,
  p_event_type text,
  p_source text,
  p_payload jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_bind jsonb;
  v_caps jsonb;
BEGIN
  SELECT w.event_ingest_binding, coalesce(w.capabilities, '[]'::jsonb)
  INTO v_bind, v_caps
  FROM wf.worker w
  WHERE w.id = p_worker_id;

  IF v_bind IS NULL THEN
    RAISE EXCEPTION 'worker event ingest denied: no event_ingest_binding (configure server-side binding)'
      USING ERRCODE = '42501';
  END IF;

  IF NOT (wf.wf_worker_is_omnibus(v_caps) OR v_caps @> '["device.adapter.ingest"]'::jsonb) THEN
    RAISE EXCEPTION 'worker event ingest denied: missing device.adapter.ingest capability'
      USING ERRCODE = '42501';
  END IF;

  IF NOT wf.wf_worker_event_binding_valid(v_bind, p_event_type, p_source, coalesce(p_payload, '{}'::jsonb)) THEN
    RAISE EXCEPTION 'worker event ingest denied: source/org/device/event_type mismatch'
      USING ERRCODE = '42501';
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION wf.wf_authorize_api_key_event_ingest(
  p_key_hash bytea,
  p_event_type text,
  p_source text,
  p_payload jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_allowed_orgs jsonb;
  v_allowed_sources jsonb;
  v_allowed_types jsonb;
  v_status text;
  v_org text;
BEGIN
  SELECT k.allowed_org_keys, k.allowed_sources, k.allowed_event_types, k.status
  INTO v_allowed_orgs, v_allowed_sources, v_allowed_types, v_status
  FROM wf.event_ingest_api_key k
  WHERE k.key_hash = p_key_hash;

  IF v_status IS NULL OR v_status IS DISTINCT FROM 'ACTIVE' THEN
    RAISE EXCEPTION 'event ingest key invalid or revoked' USING ERRCODE = '42501';
  END IF;

  IF NOT wf.wf_event_type_allowed(v_allowed_types, p_event_type) THEN
    RAISE EXCEPTION 'event ingest denied: event_type not allowed for this key' USING ERRCODE = '42501';
  END IF;

  IF NOT wf.wf_event_source_allowed(v_allowed_sources, btrim(p_source)) THEN
    RAISE EXCEPTION 'event ingest denied: source not allowed for this key' USING ERRCODE = '42501';
  END IF;

  v_org := btrim(coalesce(p_payload->>'organization_key', ''));
  IF v_org IS NULL OR v_org = '' THEN
    RAISE EXCEPTION 'event ingest denied: payload.organization_key is required' USING ERRCODE = '42501';
  END IF;

  IF NOT wf.wf_org_key_allowed(v_allowed_orgs, v_org) THEN
    RAISE EXCEPTION 'event ingest denied: organization_key not allowed for this key' USING ERRCODE = '42501';
  END IF;
END;
$$;

-- Replace worker ingest wrapper to enforce authorization before sp_ingest_event.
CREATE OR REPLACE FUNCTION wf.sp_worker_ingest_event(
  p_worker_id bigint,
  p_session_token text,
  p_identity_token text,
  p_client_ip text,
  p_event_type text,
  p_source text,
  p_idempotency_key text,
  p_payload_json jsonb DEFAULT '{}'::jsonb,
  p_correlation_key text DEFAULT NULL,
  p_occurred_at_utc timestamptz DEFAULT NULL
)
RETURNS TABLE (
  event_id bigint,
  duplicate boolean,
  applied_count int,
  ignored_count int
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, "RBAC", cfg, pg_temp
AS $$
BEGIN
  CALL wf.wf_worker_authenticate(
    p_worker_id, p_session_token, p_identity_token, p_client_ip
  );

  PERFORM wf.wf_authorize_worker_event_ingest(
    p_worker_id, btrim(p_event_type), btrim(p_source), coalesce(p_payload_json, '{}'::jsonb)
  );

  RETURN QUERY
  SELECT e.event_id, e.duplicate, e.applied_count, e.ignored_count
  FROM wf.sp_ingest_event(
    p_event_type, p_source, p_idempotency_key, p_payload_json,
    p_correlation_key, p_occurred_at_utc
  ) AS e;
END;
$$;

-- Portal / BFF path: hash-only auth (no worker session).
CREATE OR REPLACE FUNCTION wf.sp_ingest_event_with_api_key(
  p_key_hash bytea,
  p_event_type text,
  p_source text,
  p_idempotency_key text,
  p_payload_json jsonb DEFAULT '{}'::jsonb,
  p_correlation_key text DEFAULT NULL,
  p_occurred_at_utc timestamptz DEFAULT NULL
)
RETURNS TABLE (
  event_id bigint,
  duplicate boolean,
  applied_count int,
  ignored_count int
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, cfg, pg_temp
AS $$
BEGIN
  PERFORM wf.wf_authorize_api_key_event_ingest(
    p_key_hash, btrim(p_event_type), btrim(p_source), coalesce(p_payload_json, '{}'::jsonb)
  );

  RETURN QUERY
  SELECT e.event_id, e.duplicate, e.applied_count, e.ignored_count
  FROM wf.sp_ingest_event(
    p_event_type, p_source, p_idempotency_key, p_payload_json,
    p_correlation_key, p_occurred_at_utc
  ) AS e;
END;
$$;
