/*
  Action-agnostic event plane (PostgreSQL).

  Tables: wf.event_type, wf.event, wf.event_subscription, wf.event_delivery
  Engine: WAIT_EVENT columns + park/resume helpers
  Procs:  wf.sp_ingest_event, wf.sp_signal_wait, portal.sp_ingest_event

  Deploy after 08_foreach_support.sql, 01_worker_api.sql, wf_repo_create_workflow_graph.sql,
  and portal_contract_api.sql (portal schema). Additive: existing graphs unchanged.
*/

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'wf.workflow_node'::regclass
      AND c.contype = 'c'
      AND pg_get_constraintdef(c.oid) ILIKE '%node_type%'
  LOOP
    EXECUTE format('ALTER TABLE wf.workflow_node DROP CONSTRAINT %I', r.conname);
  END LOOP;

  ALTER TABLE wf.workflow_node
    ADD CONSTRAINT ck_wn_node_type CHECK (
      node_type IN (
        'ACTION','SEQUENCE','PARALLEL','IF','SWITCH','REPEAT','WHILE','FOREACH','WAIT_EVENT'
      )
    );
END $$;

ALTER TABLE wf.workflow_node ADD COLUMN IF NOT EXISTS wait_event_type text;
ALTER TABLE wf.workflow_node ADD COLUMN IF NOT EXISTS wait_correlation_var text;

CREATE TABLE IF NOT EXISTS wf.event_type (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL UNIQUE,
  payload_data_type_id bigint NULL,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

CREATE TABLE IF NOT EXISTS wf.event (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_type_id bigint NOT NULL REFERENCES wf.event_type(id),
  occurred_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  ingested_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  source text NOT NULL,
  idempotency_key text NOT NULL,
  payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  correlation_key text NULL,
  UNIQUE (source, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_event_type_ingested ON wf.event (event_type_id, ingested_at_utc DESC);
CREATE INDEX IF NOT EXISTS ix_event_correlation ON wf.event (correlation_key)
  WHERE correlation_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS wf.event_subscription (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_type_id bigint NOT NULL REFERENCES wf.event_type(id),
  workflow_version_id bigint NOT NULL REFERENCES wf.workflow_version(id) ON DELETE CASCADE,
  mode varchar(32) NOT NULL,
  filter_json jsonb NULL,
  enabled boolean NOT NULL DEFAULT true,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CHECK (mode IN ('start_instance', 'signal_wait', 'start_or_signal'))
);

CREATE INDEX IF NOT EXISTS ix_event_sub_type_enabled
  ON wf.event_subscription (event_type_id, enabled)
  WHERE enabled;

CREATE TABLE IF NOT EXISTS wf.event_delivery (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id bigint NOT NULL REFERENCES wf.event(id) ON DELETE CASCADE,
  subscription_id bigint NULL REFERENCES wf.event_subscription(id) ON DELETE SET NULL,
  workflow_instance_id bigint NULL REFERENCES wf.workflow_instance(id) ON DELETE SET NULL,
  node_execution_id bigint NULL REFERENCES wf.node_execution(id) ON DELETE SET NULL,
  status varchar(32) NOT NULL,
  detail text NULL,
  delivered_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CHECK (status IN ('applied', 'ignored', 'duplicate'))
);

CREATE INDEX IF NOT EXISTS ix_event_delivery_event ON wf.event_delivery (event_id);

CREATE OR REPLACE FUNCTION wf.wf_ensure_event_type(p_name text)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
  v_id bigint;
  v_name text := btrim(p_name);
BEGIN
  IF v_name IS NULL OR v_name = '' THEN
    RAISE EXCEPTION 'event type name is required';
  END IF;
  INSERT INTO wf.event_type (name) VALUES (v_name)
  ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
  RETURNING id INTO v_id;
  RETURN v_id;
END;
$$;

CREATE OR REPLACE FUNCTION wf.wf_event_filter_matches(p_filter jsonb, p_payload jsonb)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT CASE
    WHEN p_filter IS NULL OR p_filter = '{}'::jsonb THEN true
    ELSE NOT EXISTS (
      SELECT 1
      FROM jsonb_each(p_filter) f
      WHERE COALESCE(p_payload, '{}'::jsonb) -> f.key IS DISTINCT FROM f.value
    )
  END;
$$;

CREATE OR REPLACE FUNCTION wf.wf_event_scope_text(
  p_workflow_instance_id bigint,
  p_node_execution_id bigint,
  p_var_name text
)
RETURNS text
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_json text;
  v_trim text;
BEGIN
  IF p_var_name IS NULL OR btrim(p_var_name) = '' THEN
    RETURN NULL;
  END IF;
  v_json := wf.wf_get_scope_variable_json(p_workflow_instance_id, p_node_execution_id, p_var_name);
  IF v_json IS NULL THEN
    RETURN NULL;
  END IF;
  v_trim := btrim(v_json);
  IF left(v_trim, 1) = '"' AND right(v_trim, 1) = '"' THEN
    BEGIN
      RETURN (v_json::jsonb) #>> '{}';
    EXCEPTION WHEN others THEN
      RETURN trim(both '"' from v_trim);
    END;
  END IF;
  RETURN v_trim;
END;
$$;

CREATE OR REPLACE FUNCTION wf.wf_event_envelope(
  p_event_id bigint,
  p_event_type text,
  p_source text,
  p_correlation_key text,
  p_payload jsonb
)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT jsonb_build_object(
    'id', p_event_id,
    'type', p_event_type,
    'source', p_source,
    'correlationKey', p_correlation_key,
    'payload', COALESCE(p_payload, '{}'::jsonb)
  );
$$;

CREATE OR REPLACE PROCEDURE wf.wf_record_event_delivery(
  IN p_event_id bigint,
  IN p_subscription_id bigint,
  IN p_workflow_instance_id bigint,
  IN p_node_execution_id bigint,
  IN p_status text,
  IN p_detail text DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO wf.event_delivery (
    event_id, subscription_id, workflow_instance_id, node_execution_id, status, detail
  ) VALUES (
    p_event_id, p_subscription_id, p_workflow_instance_id, p_node_execution_id, p_status, p_detail
  );
END;
$$;

CREATE OR REPLACE FUNCTION wf.wf_signal_wait_event(
  p_event_id bigint,
  p_event_type text,
  p_payload jsonb,
  p_correlation_key text,
  p_subscription_id bigint,
  p_workflow_version_id bigint
)
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
  rec record;
  v_expected text;
  v_applied int := 0;
  v_envelope jsonb;
BEGIN
  v_envelope := wf.wf_event_envelope(
    p_event_id, p_event_type, NULL, p_correlation_key, p_payload
  );

  FOR rec IN
    SELECT ne.id AS ne_id,
           ne.workflow_instance_id AS inst_id,
           wn.wait_correlation_var AS corr_var
    FROM wf.node_execution ne
    INNER JOIN wf.workflow_node wn ON wn.id = ne.workflow_node_id
    INNER JOIN wf.workflow_instance wi ON wi.id = ne.workflow_instance_id
    WHERE wn.node_type = 'WAIT_EVENT'
      AND wn.wait_event_type = p_event_type
      AND ne.status = 'READY'
      AND wi.status = 'RUNNING'
      AND (p_workflow_version_id IS NULL OR wi.workflow_version_id = p_workflow_version_id)
    ORDER BY ne.id
  LOOP
    IF coalesce(btrim(rec.corr_var), '') <> '' THEN
      v_expected := wf.wf_event_scope_text(rec.inst_id, rec.ne_id, rec.corr_var);
      IF v_expected IS DISTINCT FROM p_correlation_key
         AND v_expected IS DISTINCT FROM (p_payload ->> rec.corr_var) THEN
        CONTINUE;
      END IF;
    END IF;

    UPDATE wf.node_execution
    SET status = 'SUCCEEDED',
        result_code = 0,
        output_json = COALESCE(p_payload, '{}'::jsonb),
        ended_at_utc = (now() AT TIME ZONE 'utc')
    WHERE id = rec.ne_id AND status = 'READY';

    IF NOT FOUND THEN
      CONTINUE;
    END IF;

    CALL wf.wf_set_scope_variable(rec.inst_id, rec.ne_id, 'event', v_envelope::text);
    CALL wf.wf_engine_on_action_complete(rec.ne_id, 0, COALESCE(p_payload, '{}'::jsonb));
    CALL wf.wf_record_event_delivery(
      p_event_id, p_subscription_id, rec.inst_id, rec.ne_id, 'applied', 'signal_wait'
    );
    v_applied := v_applied + 1;
  END LOOP;

  RETURN v_applied;
END;
$$;

CREATE OR REPLACE FUNCTION wf.wf_start_instance_from_event(
  p_event_id bigint,
  p_event_type text,
  p_source text,
  p_payload jsonb,
  p_correlation_key text,
  p_subscription_id bigint,
  p_workflow_version_id bigint
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
  v_ctx jsonb;
  v_inst bigint;
  v_envelope jsonb;
BEGIN
  v_envelope := wf.wf_event_envelope(
    p_event_id, p_event_type, p_source, p_correlation_key, p_payload
  );
  v_ctx := jsonb_build_object('event', v_envelope);
  IF p_payload ? 'projectPath' THEN
    v_ctx := v_ctx || jsonb_build_object('projectPath', p_payload->'projectPath');
  END IF;
  IF p_correlation_key IS NOT NULL THEN
    v_ctx := v_ctx || jsonb_build_object('correlationKey', to_jsonb(p_correlation_key));
  END IF;

  SELECT created.id INTO v_inst
  FROM wf.wf_repo_create_workflow_instance(p_workflow_version_id, v_ctx) AS created;

  CALL wf.sp_start_workflow_instance(v_inst);
  CALL wf.wf_record_event_delivery(
    p_event_id, p_subscription_id, v_inst, NULL, 'applied', 'start_instance'
  );
  RETURN v_inst;
END;
$$;

CREATE OR REPLACE FUNCTION wf.sp_ingest_event(
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
AS $$
DECLARE
  v_type_id bigint;
  v_event_id bigint;
  v_dup boolean := false;
  v_applied int := 0;
  v_ignored int := 0;
  v_signaled int;
  sub record;
  v_payload jsonb := COALESCE(p_payload_json, '{}'::jsonb);
  v_source text := btrim(p_source);
  v_key text := btrim(p_idempotency_key);
  v_type text := btrim(p_event_type);
BEGIN
  IF v_type IS NULL OR v_type = '' THEN
    RAISE EXCEPTION 'event_type is required';
  END IF;
  IF v_source IS NULL OR v_source = '' THEN
    RAISE EXCEPTION 'source is required';
  END IF;
  IF v_key IS NULL OR v_key = '' THEN
    RAISE EXCEPTION 'idempotency_key is required';
  END IF;

  v_type_id := wf.wf_ensure_event_type(v_type);

  INSERT INTO wf.event (
    event_type_id, occurred_at_utc, source, idempotency_key, payload_json, correlation_key
  ) VALUES (
    v_type_id,
    COALESCE(p_occurred_at_utc, now() AT TIME ZONE 'utc'),
    v_source,
    v_key,
    v_payload,
    NULLIF(btrim(p_correlation_key), '')
  )
  ON CONFLICT (source, idempotency_key) DO NOTHING
  RETURNING id INTO v_event_id;

  IF v_event_id IS NULL THEN
    SELECT e.id INTO v_event_id
    FROM wf.event e
    WHERE e.source = v_source AND e.idempotency_key = v_key;
    CALL wf.wf_record_event_delivery(v_event_id, NULL, NULL, NULL, 'duplicate', 'idempotency');
    event_id := v_event_id;
    duplicate := true;
    applied_count := 0;
    ignored_count := 1;
    RETURN NEXT;
    RETURN;
  END IF;

  FOR sub IN
    SELECT s.id, s.workflow_version_id, s.mode, s.filter_json
    FROM wf.event_subscription s
    INNER JOIN wf.workflow_version wv ON wv.id = s.workflow_version_id
    WHERE s.event_type_id = v_type_id
      AND s.enabled
      AND wv.is_active
    ORDER BY s.id
  LOOP
    IF NOT wf.wf_event_filter_matches(sub.filter_json, v_payload) THEN
      CALL wf.wf_record_event_delivery(v_event_id, sub.id, NULL, NULL, 'ignored', 'filter');
      v_ignored := v_ignored + 1;
      CONTINUE;
    END IF;

    IF sub.mode IN ('signal_wait', 'start_or_signal') THEN
      v_signaled := wf.wf_signal_wait_event(
        v_event_id, v_type, v_payload, NULLIF(btrim(p_correlation_key), ''),
        sub.id, sub.workflow_version_id
      );
      v_applied := v_applied + v_signaled;
      IF v_signaled > 0 THEN
        CONTINUE;
      END IF;
      IF sub.mode = 'signal_wait' THEN
        CALL wf.wf_record_event_delivery(v_event_id, sub.id, NULL, NULL, 'ignored', 'no_wait');
        v_ignored := v_ignored + 1;
        CONTINUE;
      END IF;
    END IF;

    IF sub.mode IN ('start_instance', 'start_or_signal') THEN
      PERFORM wf.wf_start_instance_from_event(
        v_event_id, v_type, v_source, v_payload,
        NULLIF(btrim(p_correlation_key), ''),
        sub.id, sub.workflow_version_id
      );
      v_applied := v_applied + 1;
    END IF;
  END LOOP;

  event_id := v_event_id;
  duplicate := v_dup;
  applied_count := v_applied;
  ignored_count := v_ignored;
  RETURN NEXT;
END;
$$;

CREATE OR REPLACE PROCEDURE wf.sp_signal_wait(
  IN p_event_type text,
  IN p_correlation_key text DEFAULT NULL,
  IN p_payload_json jsonb DEFAULT '{}'::jsonb,
  IN p_workflow_instance_id bigint DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_type text := btrim(p_event_type);
  v_type_id bigint;
  v_event_id bigint;
  v_version bigint;
  v_applied int;
BEGIN
  IF v_type IS NULL OR v_type = '' THEN
    RAISE EXCEPTION 'event_type is required';
  END IF;
  v_type_id := wf.wf_ensure_event_type(v_type);
  INSERT INTO wf.event (
    event_type_id, source, idempotency_key, payload_json, correlation_key
  ) VALUES (
    v_type_id,
    'signal',
    'signal:' || v_type || ':' || coalesce(p_correlation_key, '') || ':' ||
      replace(gen_random_uuid()::text, '-', ''),
    COALESCE(p_payload_json, '{}'::jsonb),
    NULLIF(btrim(p_correlation_key), '')
  )
  RETURNING id INTO v_event_id;

  IF p_workflow_instance_id IS NOT NULL THEN
    SELECT workflow_version_id INTO v_version
    FROM wf.workflow_instance WHERE id = p_workflow_instance_id;
  END IF;

  v_applied := wf.wf_signal_wait_event(
    v_event_id, v_type, COALESCE(p_payload_json, '{}'::jsonb),
    NULLIF(btrim(p_correlation_key), ''), NULL, v_version
  );
  IF v_applied = 0 THEN
    CALL wf.wf_record_event_delivery(v_event_id, NULL, p_workflow_instance_id, NULL, 'ignored', 'no_wait');
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.sp_ingest_event(
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
LANGUAGE sql
AS $$
  SELECT * FROM wf.sp_ingest_event(
    p_event_type, p_source, p_idempotency_key, p_payload_json, p_correlation_key, p_occurred_at_utc
  );
$$;
