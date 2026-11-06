/*
  Worker-authenticated event ingest (adapter plane).
  Prerequisites: wf_event_plane.sql (wf.sp_ingest_event), wf_worker_session_api.sql (wf.wf_worker_authenticate)
*/

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

  RETURN QUERY
  SELECT e.event_id, e.duplicate, e.applied_count, e.ignored_count
  FROM wf.sp_ingest_event(
    p_event_type, p_source, p_idempotency_key, p_payload_json,
    p_correlation_key, p_occurred_at_utc
  ) AS e;
END;
$$;
