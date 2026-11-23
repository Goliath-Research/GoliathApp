/*
  Platform history ledger (H1): append-only, hash-chained history tables.

  Every table registered here becomes a ledger:
    * rows can be inserted, never updated;
    * rows can be deleted only inside a retention purge that the platform authorized for the
      current transaction (portal.ledger_purge_authorization); every purged row leaves a
      tombstone (sequence number + row hash), so the chain still verifies and gaps are explained;
    * TRUNCATE is refused;
    * each row carries ledger_seq (contiguous per ledger), txid (the writing transaction),
      prev_hash and row_hash = sha256(prev_hash || canonical row JSON).

  portal.fn_ledger_verify(ledger) re-computes the chain and reports breaks. portal.fn_ledger_checkpoint()
  returns the head of every ledger so operators can anchor it outside the database.

  Generic: no product names. Idempotent: safe to re-run with apply_schema.sh.
  See docs/history-and-audit.md.
*/

BEGIN;

CREATE TABLE IF NOT EXISTS portal.ledger_registry (
  ledger_name text PRIMARY KEY,
  table_regclass regclass NOT NULL,
  description text NOT NULL DEFAULT '',
  registered_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

-- Natural-key columns of ledgers written with INSERT … ON CONFLICT DO NOTHING (for example
-- idempotent event ingest). A duplicate is skipped before it takes a sequence number.
ALTER TABLE portal.ledger_registry ADD COLUMN IF NOT EXISTS dedupe_columns text[] NULL;

CREATE TABLE IF NOT EXISTS portal.ledger_head (
  ledger_name text PRIMARY KEY REFERENCES portal.ledger_registry (ledger_name),
  last_seq bigint NOT NULL DEFAULT 0,
  last_hash bytea NULL,
  updated_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc')
);

-- Rows a purge removed: the chain links through these.
CREATE TABLE IF NOT EXISTS portal.ledger_tombstone (
  ledger_name text NOT NULL REFERENCES portal.ledger_registry (ledger_name),
  ledger_seq bigint NOT NULL,
  row_hash bytea NOT NULL,
  purge_id bigint NULL,
  purged_txid bigint NOT NULL,
  purged_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT "PK_portal_ledger_tombstone" PRIMARY KEY (ledger_name, ledger_seq)
);

-- Written only by SECURITY DEFINER purge functions; ledger guards read it.
CREATE TABLE IF NOT EXISTS portal.ledger_purge_authorization (
  txid bigint NOT NULL,
  ledger_name text NOT NULL REFERENCES portal.ledger_registry (ledger_name),
  purge_id bigint NULL,
  created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'),
  CONSTRAINT "PK_portal_ledger_purge_authorization" PRIMARY KEY (txid, ledger_name)
);

REVOKE ALL ON portal.ledger_registry, portal.ledger_head, portal.ledger_tombstone,
  portal.ledger_purge_authorization FROM PUBLIC;

CREATE OR REPLACE FUNCTION portal.fn_ledger_current_txid()
RETURNS bigint
LANGUAGE sql
VOLATILE
AS $$
  SELECT pg_current_xact_id()::text::bigint;
$$;

/*
  Canonical bytes hashed for one ledger row: the row as jsonb, without row_hash, with null keys
  removed (so a ledger table can later gain nullable columns without breaking old rows).
  Runs with fixed TimeZone / bytea / float settings so the text is identical on every session.
*/
CREATE OR REPLACE FUNCTION portal.fn_ledger_row_hash(p_prev_hash bytea, p_row jsonb)
RETURNS bytea
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT sha256(
    COALESCE(p_prev_hash, '\x'::bytea)
    || convert_to(jsonb_strip_nulls(p_row - 'row_hash')::text, 'UTF8')
  );
$$;

CREATE OR REPLACE FUNCTION portal.fn_ledger_before_insert()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
SET "TimeZone" = 'UTC'
SET bytea_output = 'hex'
SET extra_float_digits = '1'
AS $$
DECLARE
  v_name text := TG_ARGV[0];
  v_seq bigint;
  v_prev bytea;
  v_dedupe text[];
  v_dup boolean;
BEGIN
  INSERT INTO portal.ledger_head (ledger_name) VALUES (v_name) ON CONFLICT DO NOTHING;
  SELECT h.last_seq, h.last_hash INTO v_seq, v_prev
  FROM portal.ledger_head h
  WHERE h.ledger_name = v_name
  FOR UPDATE;

  -- The head lock serializes writers, so this check sees every committed duplicate.
  SELECT r.dedupe_columns INTO v_dedupe FROM portal.ledger_registry r WHERE r.ledger_name = v_name;
  IF v_dedupe IS NOT NULL AND cardinality(v_dedupe) > 0 THEN
    EXECUTE format(
      'SELECT EXISTS (SELECT 1 FROM %I.%I t WHERE %s)',
      TG_TABLE_SCHEMA, TG_TABLE_NAME,
      (SELECT string_agg(format('t.%1$I IS NOT DISTINCT FROM ($1).%1$I', c), ' AND ') FROM unnest(v_dedupe) c)
    ) INTO v_dup USING NEW;
    IF v_dup THEN
      RETURN NULL;
    END IF;
  END IF;

  NEW.ledger_seq := v_seq + 1;
  NEW.txid := COALESCE(NEW.txid, portal.fn_ledger_current_txid());
  NEW.prev_hash := v_prev;
  NEW.row_hash := NULL;
  NEW.row_hash := portal.fn_ledger_row_hash(v_prev, to_jsonb(NEW));

  UPDATE portal.ledger_head
  SET last_seq = NEW.ledger_seq,
      last_hash = NEW.row_hash,
      updated_at_utc = (now() AT TIME ZONE 'utc')
  WHERE ledger_name = v_name;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_ledger_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
DECLARE
  v_name text := TG_ARGV[0];
  v_purge_id bigint;
  v_authorized boolean := false;
BEGIN
  IF TG_OP = 'TRUNCATE' THEN
    RAISE EXCEPTION 'ledger % is append-only: TRUNCATE is not allowed', v_name USING ERRCODE = 'GS409';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'ledger % is append-only: rows cannot be updated', v_name USING ERRCODE = 'GS409';
  END IF;

  SELECT true, a.purge_id INTO v_authorized, v_purge_id
  FROM portal.ledger_purge_authorization a
  WHERE a.txid = portal.fn_ledger_current_txid()
    AND a.ledger_name = v_name;

  IF NOT COALESCE(v_authorized, false) THEN
    RAISE EXCEPTION 'ledger % is append-only: rows are removed only by an authorized retention purge', v_name
      USING ERRCODE = 'GS409';
  END IF;

  INSERT INTO portal.ledger_tombstone (ledger_name, ledger_seq, row_hash, purge_id, purged_txid)
  VALUES (v_name, OLD.ledger_seq, OLD.row_hash, v_purge_id, portal.fn_ledger_current_txid());
  RETURN OLD;
END;
$$;

/*
  Make a table a ledger. Adds the four ledger columns, backfills the chain for existing rows
  (ordered by p_order_by) the first time, then installs the insert and guard triggers.
*/
CREATE OR REPLACE FUNCTION portal.sp_ledger_register(
  p_ledger_name text,
  p_table regclass,
  p_order_by text,
  p_description text DEFAULT '',
  p_dedupe_columns text[] DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SET search_path = portal, pg_temp
SET "TimeZone" = 'UTC'
SET bytea_output = 'hex'
SET extra_float_digits = '1'
SET client_min_messages = warning
AS $$
DECLARE
  v_rec record;
  v_seq bigint := 0;
  v_prev bytea := NULL;
  v_hash bytea;
  v_new boolean;
  v_ctid tid;
  v_doc jsonb;
BEGIN
  EXECUTE format('ALTER TABLE %s ADD COLUMN IF NOT EXISTS ledger_seq bigint', p_table);
  EXECUTE format('ALTER TABLE %s ADD COLUMN IF NOT EXISTS txid bigint', p_table);
  EXECUTE format('ALTER TABLE %s ADD COLUMN IF NOT EXISTS prev_hash bytea', p_table);
  EXECUTE format('ALTER TABLE %s ADD COLUMN IF NOT EXISTS row_hash bytea', p_table);

  v_new := NOT EXISTS (SELECT 1 FROM portal.ledger_registry r WHERE r.ledger_name = p_ledger_name);

  INSERT INTO portal.ledger_registry (ledger_name, table_regclass, description, dedupe_columns)
  VALUES (p_ledger_name, p_table, COALESCE(p_description, ''), p_dedupe_columns)
  ON CONFLICT (ledger_name) DO UPDATE
    SET table_regclass = EXCLUDED.table_regclass,
        description = EXCLUDED.description,
        dedupe_columns = EXCLUDED.dedupe_columns;

  IF v_new OR NOT EXISTS (SELECT 1 FROM portal.ledger_head h WHERE h.ledger_name = p_ledger_name) THEN
    -- First registration: chain the rows that already exist, oldest first.
    EXECUTE format('DROP TRIGGER IF EXISTS trg_ledger_guard ON %s', p_table);
    FOR v_rec IN EXECUTE format(
      'SELECT ctid AS row_ctid FROM %s t ORDER BY %s', p_table, p_order_by
    )
    LOOP
      v_seq := v_seq + 1;
      EXECUTE format(
        'UPDATE %s t SET ledger_seq = $1, prev_hash = $2, txid = NULL, row_hash = NULL '
        'WHERE t.ctid = $3 RETURNING t.ctid, to_jsonb(t.*)',
        p_table
      ) INTO v_ctid, v_doc USING v_seq, v_prev, v_rec.row_ctid;
      v_hash := portal.fn_ledger_row_hash(v_prev, v_doc);
      EXECUTE format('UPDATE %s t SET row_hash = $1 WHERE t.ctid = $2', p_table) USING v_hash, v_ctid;
      v_prev := v_hash;
    END LOOP;
    INSERT INTO portal.ledger_head (ledger_name, last_seq, last_hash)
    VALUES (p_ledger_name, v_seq, v_prev)
    ON CONFLICT (ledger_name) DO UPDATE SET last_seq = EXCLUDED.last_seq, last_hash = EXCLUDED.last_hash;
  END IF;

  EXECUTE format(
    'CREATE UNIQUE INDEX IF NOT EXISTS %I ON %s (ledger_seq)',
    'ux_ledger_seq_' || md5(p_ledger_name), p_table
  );

  EXECUTE format('DROP TRIGGER IF EXISTS trg_ledger_before_insert ON %s', p_table);
  EXECUTE format(
    'CREATE TRIGGER trg_ledger_before_insert BEFORE INSERT ON %s FOR EACH ROW EXECUTE FUNCTION portal.fn_ledger_before_insert(%L)',
    p_table, p_ledger_name
  );
  EXECUTE format('DROP TRIGGER IF EXISTS trg_ledger_guard ON %s', p_table);
  EXECUTE format(
    'CREATE TRIGGER trg_ledger_guard BEFORE UPDATE OR DELETE ON %s FOR EACH ROW EXECUTE FUNCTION portal.fn_ledger_guard(%L)',
    p_table, p_ledger_name
  );
  EXECUTE format('DROP TRIGGER IF EXISTS trg_ledger_no_truncate ON %s', p_table);
  EXECUTE format(
    'CREATE TRIGGER trg_ledger_no_truncate BEFORE TRUNCATE ON %s FOR EACH STATEMENT EXECUTE FUNCTION portal.fn_ledger_guard(%L)',
    p_table, p_ledger_name
  );

  EXECUTE format('REVOKE UPDATE, DELETE, TRUNCATE ON %s FROM PUBLIC', p_table);
END;
$$;

/*
  Re-compute a ledger's chain. Returns one row per problem (empty result = intact):
    missing_seq    a sequence number with neither a row nor a tombstone (rows removed outside a purge)
    prev_mismatch  prev_hash does not equal the hash of the previous entry
    hash_mismatch  the row's content no longer matches its row_hash (edited outside the platform)
    head_mismatch  the head does not match the last entry
*/
CREATE OR REPLACE FUNCTION portal.fn_ledger_verify(p_ledger_name text)
RETURNS TABLE (ledger_seq bigint, problem text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
SET "TimeZone" = 'UTC'
SET bytea_output = 'hex'
SET extra_float_digits = '1'
AS $$
#variable_conflict use_column
DECLARE
  v_table regclass;
  v_rec record;
  v_expected bigint := 1;
  v_prev bytea := NULL;
  v_head record;
BEGIN
  SELECT r.table_regclass INTO v_table FROM portal.ledger_registry r WHERE r.ledger_name = p_ledger_name;
  IF v_table IS NULL THEN
    RAISE EXCEPTION 'unknown ledger %', p_ledger_name USING ERRCODE = 'GS404';
  END IF;

  FOR v_rec IN EXECUTE format(
    $q$
      SELECT x.seq, x.prev_hash, x.row_hash, x.doc
      FROM (
        SELECT t.ledger_seq AS seq, t.prev_hash, t.row_hash, to_jsonb(t) AS doc FROM %s t
        UNION ALL
        SELECT s.ledger_seq, NULL::bytea, s.row_hash, NULL::jsonb
        FROM portal.ledger_tombstone s WHERE s.ledger_name = %L
      ) x
      ORDER BY x.seq
    $q$, v_table, p_ledger_name)
  LOOP
    WHILE v_rec.seq > v_expected LOOP
      ledger_seq := v_expected; problem := 'missing_seq'; RETURN NEXT;
      v_expected := v_expected + 1;
      v_prev := NULL;
    END LOOP;
    IF v_rec.doc IS NOT NULL THEN
      IF v_rec.seq > 1 AND v_prev IS NOT NULL AND v_rec.prev_hash IS DISTINCT FROM v_prev THEN
        ledger_seq := v_rec.seq; problem := 'prev_mismatch'; RETURN NEXT;
      END IF;
      IF portal.fn_ledger_row_hash(v_rec.prev_hash, v_rec.doc) IS DISTINCT FROM v_rec.row_hash THEN
        ledger_seq := v_rec.seq; problem := 'hash_mismatch'; RETURN NEXT;
      END IF;
    END IF;
    v_prev := v_rec.row_hash;
    v_expected := v_rec.seq + 1;
  END LOOP;

  SELECT h.last_seq, h.last_hash INTO v_head FROM portal.ledger_head h WHERE h.ledger_name = p_ledger_name;
  IF v_head.last_seq IS DISTINCT FROM (v_expected - 1)
     OR (v_head.last_seq > 0 AND v_head.last_hash IS DISTINCT FROM v_prev) THEN
    ledger_seq := v_head.last_seq; problem := 'head_mismatch'; RETURN NEXT;
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION portal.fn_ledger_checkpoint()
RETURNS TABLE (ledger_name text, last_seq bigint, last_hash_hex text, taken_at_utc timestamptz)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  SELECT r.ledger_name, COALESCE(h.last_seq, 0), encode(h.last_hash, 'hex'), (now() AT TIME ZONE 'utc')
  FROM portal.ledger_registry r
  LEFT JOIN portal.ledger_head h ON h.ledger_name = r.ledger_name
  ORDER BY r.ledger_name;
$$;

CREATE OR REPLACE FUNCTION portal.fn_ledger_verify_all()
RETURNS TABLE (ledger_name text, ledger_seq bigint, problem text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  SELECT r.ledger_name, v.ledger_seq, v.problem
  FROM portal.ledger_registry r
  CROSS JOIN LATERAL portal.fn_ledger_verify(r.ledger_name) v
  ORDER BY r.ledger_name, v.ledger_seq;
$$;

-- History rows keep the ids they refer to; they must not be rewritten by cascading FKs.
DO $drop_delivery_fks$
DECLARE
  v_con record;
BEGIN
  FOR v_con IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'wf.event_delivery'::regclass
      AND c.contype = 'f'
      AND c.confrelid IN (
        'wf.workflow_instance'::regclass,
        'wf.node_execution'::regclass,
        'wf.event_subscription'::regclass
      )
  LOOP
    EXECUTE format('ALTER TABLE wf.event_delivery DROP CONSTRAINT %I', v_con.conname);
  END LOOP;
END
$drop_delivery_fks$;

DO $register_ledgers$
BEGIN
  PERFORM portal.sp_ledger_register('portal.record_editor_audit', 'portal.record_editor_audit', 'audit_id',
  'Record editor saves, deletes and fleet/run actions');
  PERFORM portal.sp_ledger_register('portal.model_authoring_audit', 'portal.model_authoring_audit', 'audit_id',
  'Child-namespace model authoring');
  PERFORM portal.sp_ledger_register('portal.security_admin_audit', 'portal.security_admin_audit', 'audit_id',
  'Users, roles, grants, class and object ACL changes');
  PERFORM portal.sp_ledger_register('portal.god_architect_audit', 'portal.god_architect_audit', 'audit_id',
  'platform/* catalog changes and God Architect grants');
  PERFORM portal.sp_ledger_register('portal.session_active_role_audit', 'portal.session_active_role_audit', 'audit_id',
  'Active role selection per session');
  PERFORM portal.sp_ledger_register('portal.external_identity_link_audit', 'portal.external_identity_link_audit', 'audit_id',
  'External identity links at first sign-in');
  PERFORM portal.sp_ledger_register('onboarding.audit_log', '"Onboarding"."AuditLog"', '"AuditID"',
  'Invitation lifecycle');
  PERFORM portal.sp_ledger_register('wf.event', 'wf.event', 'id',
  'Ingested events (facts)', ARRAY['source', 'idempotency_key']);
  PERFORM portal.sp_ledger_register('wf.event_delivery', 'wf.event_delivery', 'id',
  'How each event was applied to subscriptions and runs');
END
$register_ledgers$;

COMMIT;
