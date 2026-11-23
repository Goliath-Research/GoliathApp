/*
  Workflow run history and retention (H3).

  * wf.run_history is a platform ledger (append-only, hash-chained) recording every workflow instance
    and node execution status transition and every task lease change, so the run record (including
    which worker held each task) survives after runtime rows change.
  * Workflow instances and node executions cannot be deleted except by wf.sp_purge_run_history,
    the PurgeExpiredRuns method of platform/RetentionPolicy. Without a matching policy, runs are kept
    forever; a legal hold blocks purging. A purge removes the run's history rows (each leaves a
    tombstone, so the chain still verifies) and appends a run.purge entry recording what was removed,
    under which policy, by whom.
  * wf.sp_delete_workflow_def no longer cascades into run history: deleting a definition together with
    its instances goes through the same retention purge.

  See docs/history-and-audit.md (section 6).
*/

BEGIN;

CREATE TABLE IF NOT EXISTS wf.run_history (
  history_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  change_kind text NOT NULL,
  workflow_instance_id bigint NOT NULL,
  workflow_version_id bigint NULL,
  node_execution_id bigint NULL,
  workflow_node_id bigint NULL,
  worker_id bigint NULL,
  status_before text NULL,
  status_after text NULL,
  attempt_no integer NULL,
  result_code integer NULL,
  engine_error_code integer NULL,
  engine_error_message text NULL,
  detail jsonb NULL,
  actor_user_id integer NULL,
  db_role text NOT NULL DEFAULT current_user,
  recorded_at_utc timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_run_history_kind CHECK (change_kind IN (
    'instance.create', 'instance.status', 'instance.baseline',
    'node.create', 'node.status', 'node.baseline',
    'lease.acquire', 'lease.transfer', 'lease.release',
    'run.purge'
  ))
);

CREATE INDEX IF NOT EXISTS ix_run_history_instance ON wf.run_history (workflow_instance_id, history_id);
CREATE INDEX IF NOT EXISTS ix_run_history_recorded ON wf.run_history (recorded_at_utc);

REVOKE ALL ON wf.run_history FROM PUBLIC;

/* True while wf.sp_purge_run_history is running in this transaction. */
CREATE OR REPLACE FUNCTION wf.fn_run_purge_authorized()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = portal, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM portal.ledger_purge_authorization a
    WHERE a.txid = portal.fn_ledger_current_txid() AND a.ledger_name = 'wf.run_history'
  );
$$;

CREATE OR REPLACE FUNCTION wf.fn_run_history_capture()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, portal, pg_temp
AS $$
DECLARE
  v_actor integer := NULLIF(current_setting('goliath.actor_user_id', true), '')::integer;
  v_instance bigint;
BEGIN
  IF TG_TABLE_NAME = 'workflow_instance' THEN
    INSERT INTO wf.run_history (
      change_kind, workflow_instance_id, workflow_version_id, status_before, status_after, actor_user_id
    ) VALUES (
      CASE WHEN TG_OP = 'INSERT' THEN 'instance.create' ELSE 'instance.status' END,
      NEW.id, NEW.workflow_version_id,
      CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.status END,
      NEW.status, v_actor
    );
    RETURN NULL;
  END IF;

  IF TG_TABLE_NAME = 'node_execution' THEN
    INSERT INTO wf.run_history (
      change_kind, workflow_instance_id, node_execution_id, workflow_node_id, worker_id,
      status_before, status_after, attempt_no, result_code, engine_error_code, engine_error_message,
      detail, actor_user_id
    ) VALUES (
      CASE WHEN TG_OP = 'INSERT' THEN 'node.create' ELSE 'node.status' END,
      NEW.workflow_instance_id, NEW.id, NEW.workflow_node_id, NEW.completed_by_worker_id,
      CASE WHEN TG_OP = 'INSERT' THEN NULL ELSE OLD.status END,
      NEW.status, NEW.attempt_no, NEW.result_code, NEW.engine_error_code, NEW.engine_error_message,
      CASE WHEN NEW.status IN ('SUCCEEDED', 'FAILED', 'SKIPPED', 'CANCELLED')
        THEN jsonb_strip_nulls(jsonb_build_object('output', NEW.output_json, 'iteration_no', NEW.iteration_no))
        ELSE NULL END,
      v_actor
    );
    RETURN NULL;
  END IF;

  IF TG_TABLE_NAME = 'task_lease' THEN
    IF TG_OP = 'DELETE' AND wf.fn_run_purge_authorized() THEN
      RETURN NULL;  -- the run is being purged; its history goes with it
    END IF;
    SELECT ne.workflow_instance_id INTO v_instance
    FROM wf.node_execution ne
    WHERE ne.id = CASE WHEN TG_OP = 'DELETE' THEN OLD.node_execution_id ELSE NEW.node_execution_id END;
    IF v_instance IS NULL THEN
      RETURN NULL;
    END IF;
    INSERT INTO wf.run_history (
      change_kind, workflow_instance_id, node_execution_id, worker_id, detail, actor_user_id
    ) VALUES (
      CASE TG_OP WHEN 'INSERT' THEN 'lease.acquire' WHEN 'UPDATE' THEN 'lease.transfer' ELSE 'lease.release' END,
      v_instance,
      CASE WHEN TG_OP = 'DELETE' THEN OLD.node_execution_id ELSE NEW.node_execution_id END,
      CASE WHEN TG_OP = 'DELETE' THEN OLD.worker_id ELSE NEW.worker_id END,
      CASE WHEN TG_OP = 'UPDATE' THEN jsonb_build_object('previous_worker_id', OLD.worker_id) ELSE NULL END,
      v_actor
    );
    RETURN NULL;
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION wf.fn_run_delete_guard()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, portal, pg_temp
AS $$
BEGIN
  IF TG_OP = 'TRUNCATE' OR NOT wf.fn_run_purge_authorized() THEN
    RAISE EXCEPTION '% rows are run history: remove them only with wf.sp_purge_run_history under a retention policy',
      TG_TABLE_NAME USING ERRCODE = 'GS409';
  END IF;
  RETURN OLD;
END;
$$;

-- First install: record the current state of existing runs.
DO $baseline$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM wf.run_history) THEN
    INSERT INTO wf.run_history (change_kind, workflow_instance_id, workflow_version_id, status_after, detail)
    SELECT 'instance.baseline', wi.id, wi.workflow_version_id, wi.status,
           jsonb_strip_nulls(jsonb_build_object('started_at_utc', wi.started_at_utc, 'completed_at_utc', wi.completed_at_utc))
    FROM wf.workflow_instance wi ORDER BY wi.id;

    INSERT INTO wf.run_history (
      change_kind, workflow_instance_id, node_execution_id, workflow_node_id, worker_id, status_after,
      attempt_no, result_code, engine_error_code, engine_error_message
    )
    SELECT 'node.baseline', ne.workflow_instance_id, ne.id, ne.workflow_node_id, ne.completed_by_worker_id,
           ne.status, ne.attempt_no, ne.result_code, ne.engine_error_code, ne.engine_error_message
    FROM wf.node_execution ne ORDER BY ne.id;
  END IF;
END
$baseline$;

DO $register$
BEGIN
  PERFORM portal.sp_ledger_register(
    'wf.run_history', 'wf.run_history', 'history_id',
    'Workflow instance and node status transitions and task leases'
  );
END
$register$;

DROP TRIGGER IF EXISTS trg_run_history_instance_insert ON wf.workflow_instance;
CREATE TRIGGER trg_run_history_instance_insert
  AFTER INSERT ON wf.workflow_instance
  FOR EACH ROW EXECUTE FUNCTION wf.fn_run_history_capture();
DROP TRIGGER IF EXISTS trg_run_history_instance_status ON wf.workflow_instance;
CREATE TRIGGER trg_run_history_instance_status
  AFTER UPDATE OF status ON wf.workflow_instance
  FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
  EXECUTE FUNCTION wf.fn_run_history_capture();

DROP TRIGGER IF EXISTS trg_run_history_node_insert ON wf.node_execution;
CREATE TRIGGER trg_run_history_node_insert
  AFTER INSERT ON wf.node_execution
  FOR EACH ROW EXECUTE FUNCTION wf.fn_run_history_capture();
DROP TRIGGER IF EXISTS trg_run_history_node_status ON wf.node_execution;
CREATE TRIGGER trg_run_history_node_status
  AFTER UPDATE OF status ON wf.node_execution
  FOR EACH ROW WHEN (OLD.status IS DISTINCT FROM NEW.status)
  EXECUTE FUNCTION wf.fn_run_history_capture();

DROP TRIGGER IF EXISTS trg_run_history_lease_insert ON wf.task_lease;
CREATE TRIGGER trg_run_history_lease_insert
  AFTER INSERT OR DELETE ON wf.task_lease
  FOR EACH ROW EXECUTE FUNCTION wf.fn_run_history_capture();
DROP TRIGGER IF EXISTS trg_run_history_lease_transfer ON wf.task_lease;
CREATE TRIGGER trg_run_history_lease_transfer
  AFTER UPDATE OF worker_id ON wf.task_lease
  FOR EACH ROW WHEN (OLD.worker_id IS DISTINCT FROM NEW.worker_id)
  EXECUTE FUNCTION wf.fn_run_history_capture();

DROP TRIGGER IF EXISTS trg_run_guard_instance_delete ON wf.workflow_instance;
CREATE TRIGGER trg_run_guard_instance_delete
  BEFORE DELETE ON wf.workflow_instance
  FOR EACH ROW EXECUTE FUNCTION wf.fn_run_delete_guard();
DROP TRIGGER IF EXISTS trg_run_guard_instance_truncate ON wf.workflow_instance;
CREATE TRIGGER trg_run_guard_instance_truncate
  BEFORE TRUNCATE ON wf.workflow_instance
  FOR EACH STATEMENT EXECUTE FUNCTION wf.fn_run_delete_guard();
DROP TRIGGER IF EXISTS trg_run_guard_node_delete ON wf.node_execution;
CREATE TRIGGER trg_run_guard_node_delete
  BEFORE DELETE ON wf.node_execution
  FOR EACH ROW EXECUTE FUNCTION wf.fn_run_delete_guard();
DROP TRIGGER IF EXISTS trg_run_guard_node_truncate ON wf.node_execution;
CREATE TRIGGER trg_run_guard_node_truncate
  BEFORE TRUNCATE ON wf.node_execution
  FOR EACH STATEMENT EXECUTE FUNCTION wf.fn_run_delete_guard();

/* platform/RetentionPolicy: a Meta class; only God Architect may create or change policies. */
DO $retention_class$
DECLARE
  v_text bigint;
  v_int bigint;
  v_bool bigint;
  v_class int;
BEGIN
  SELECT id INTO v_text FROM wf.data_type WHERE name = 'platform/security/Text' AND version = '1.0';
  SELECT id INTO v_int FROM wf.data_type WHERE name = 'platform/security/Integer' AND version = '1.0';
  SELECT id INTO v_bool FROM wf.data_type WHERE name = 'platform/security/Boolean' AND version = '1.0';

  INSERT INTO "Meta"."Classes" ("Name", "ParentID")
  SELECT 'platform/RetentionPolicy', (SELECT c."ID" FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Entity')
  WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = 'platform/RetentionPolicy');
  PERFORM "Meta".sp_backfill_all_class_hierarchies();

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/RetentionPolicy';

  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
  SELECT v_class, f.name, f.type_id, f.req, f.descr
  FROM (VALUES
    ('Label', v_text, true, 'Display label'),
    ('RecordKind', v_text, true, 'Kind of record governed; wf.run = workflow runs'),
    ('WorkflowName', v_text, false, 'Limit to one workflow definition; empty = every workflow'),
    ('RetentionDays', v_int, true, 'Days a finished record is kept before it may be purged'),
    ('LegalHold', v_bool, true, 'When true, nothing this policy governs may be purged')
  ) AS f(name, type_id, req, descr)
  WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);

  INSERT INTO "Meta"."Methods" ("ClassID", "Name", "Description", "ImplKind", "ImplRef", "IsAbstract")
  SELECT v_class, 'PurgeExpiredRuns',
         'Purge workflow runs whose retention period has passed (wf.sp_purge_run_history)',
         'sql', 'wf.sp_purge_run_history', false
  WHERE NOT EXISTS (
    SELECT 1 FROM "Meta"."Methods" m WHERE m."ClassID" = v_class AND m."Name" = 'PurgeExpiredRuns'
  );
END
$retention_class$;

SELECT portal.sp_platform_god_architect_class_acl_sync();

/* Retention policies that govern runs of a workflow: those naming it, and general ones. */
CREATE OR REPLACE FUNCTION wf.fn_run_retention_policies(p_workflow_name text)
RETURNS TABLE (policy_obj_id integer, specific boolean, retention_days integer, legal_hold boolean)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = wf, "Meta", pg_temp
AS $$
  SELECT p.obj_id,
         COALESCE(p.doc ->> 'WorkflowName', '') <> '',
         (p.doc ->> 'RetentionDays')::integer,
         COALESCE((p.doc ->> 'LegalHold')::boolean, false)
  FROM (
    SELECT o."ID" AS obj_id, "Meta".fn_merged_obj_document(o."ID") AS doc
    FROM "Meta"."Objs" o
    JOIN "Meta"."Classes" c ON c."ID" = o."ClassID"
    WHERE c."Name" = 'platform/RetentionPolicy'
  ) p
  WHERE p.doc ->> 'RecordKind' = 'wf.run'
    AND (COALESCE(p.doc ->> 'WorkflowName', '') = '' OR p.doc ->> 'WorkflowName' = p_workflow_name);
$$;

/*
  The policy that decides a run's retention: a policy naming the workflow wins over general ones;
  among equals the longest retention wins. A legal hold on any matching policy applies.
*/
CREATE OR REPLACE FUNCTION wf.fn_run_retention(p_workflow_instance_id bigint)
RETURNS TABLE (policy_obj_id integer, retention_days integer, legal_hold boolean)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = wf, "Meta", pg_temp
AS $$
  WITH m AS (
    SELECT r.*
    FROM wf.workflow_instance wi
    JOIN wf.workflow_version wv ON wv.id = wi.workflow_version_id
    JOIN wf.workflow_def wd ON wd.id = wv.workflow_def_id
    CROSS JOIN LATERAL wf.fn_run_retention_policies(wd.name) r
    WHERE wi.id = p_workflow_instance_id
  ), decisive AS (
    SELECT m.policy_obj_id, m.retention_days
    FROM m
    ORDER BY m.specific DESC, m.retention_days DESC NULLS FIRST, m.policy_obj_id
    LIMIT 1
  )
  SELECT d.policy_obj_id, d.retention_days, (SELECT bool_or(m.legal_hold) FROM m)
  FROM decisive d;
$$;

/*
  Why a run may not be purged now; no rows means it may. Later slices add blockers
  (for example electronic signatures) by replacing this function.
*/
CREATE OR REPLACE FUNCTION wf.fn_run_purge_blockers(p_workflow_instance_id bigint)
RETURNS TABLE (blocker text, policy_obj_id integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = wf, "Meta", pg_temp
AS $$
DECLARE
  v_wi record;
  v_ret record;
  v_ref timestamptz;
BEGIN
  SELECT wi.* INTO v_wi FROM wf.workflow_instance wi WHERE wi.id = p_workflow_instance_id;
  IF NOT FOUND THEN
    RETURN QUERY SELECT 'instance not found'::text, NULL::integer;
    RETURN;
  END IF;

  SELECT * INTO v_ret FROM wf.fn_run_retention(p_workflow_instance_id);
  IF v_ret.policy_obj_id IS NULL THEN
    RETURN QUERY SELECT 'no retention policy: runs are kept forever'::text, NULL::integer;
    RETURN;
  END IF;
  IF v_ret.retention_days IS NULL OR v_ret.retention_days < 0 THEN
    RETURN QUERY SELECT 'retention policy has no valid RetentionDays: runs are kept'::text, v_ret.policy_obj_id;
    RETURN;
  END IF;
  IF v_ret.legal_hold THEN
    RETURN QUERY SELECT 'legal hold'::text, v_ret.policy_obj_id;
    RETURN;
  END IF;
  IF v_wi.status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED') AND v_ret.retention_days > 0 THEN
    RETURN QUERY SELECT 'run is not finished'::text, v_ret.policy_obj_id;
    RETURN;
  END IF;

  -- Age reference: the earliest of the run's completion/start time and its last recorded transition.
  -- run_history.recorded_at_utc is now(), an absolute instant. The engine writes its *_at_utc columns
  -- as UTC wall-clock values, which a session in a time zone west of UTC stores hours in the future;
  -- taking LEAST keeps such a run purgeable on time instead of hours late. (LEAST ignores NULLs.)
  v_ref := LEAST(
    (SELECT max(h.recorded_at_utc) FROM wf.run_history h WHERE h.workflow_instance_id = v_wi.id),
    v_wi.completed_at_utc, v_wi.started_at_utc
  );
  IF v_ref IS NOT NULL AND v_ref > now() - make_interval(days => v_ret.retention_days) THEN
    RETURN QUERY SELECT format('retention period of %s days has not passed', v_ret.retention_days),
                        v_ret.policy_obj_id;
    RETURN;
  END IF;
END;
$$;

/*
  platform/RetentionPolicy.PurgeExpiredRuns. For each requested instance: purge it if no blocker
  applies, otherwise report why not. With p_require_all, any blocker aborts the whole call.
*/
CREATE OR REPLACE FUNCTION wf.sp_purge_run_history(
  p_workflow_instance_ids bigint[],
  p_reason text DEFAULT NULL,
  p_require_all boolean DEFAULT false
)
RETURNS TABLE (workflow_instance_id bigint, purged boolean, reason text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = wf, portal, "Meta", pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_id bigint;
  v_blocker text;
  v_ok bigint[] := ARRAY[]::bigint[];
  v_status text;
  v_version bigint;
  v_nodes integer;
  v_rows integer;
  v_policy integer;
  v_txid bigint := portal.fn_ledger_current_txid();
BEGIN
  FOREACH v_id IN ARRAY COALESCE(p_workflow_instance_ids, ARRAY[]::bigint[]) LOOP
    SELECT b.blocker INTO v_blocker FROM wf.fn_run_purge_blockers(v_id) b LIMIT 1;
    IF v_blocker IS NOT NULL THEN
      IF p_require_all THEN
        RAISE EXCEPTION 'workflow instance % cannot be purged: %', v_id, v_blocker USING ERRCODE = 'GS409';
      END IF;
      workflow_instance_id := v_id; purged := false; reason := v_blocker;
      RETURN NEXT;
    ELSE
      v_ok := v_ok || v_id;
    END IF;
  END LOOP;

  IF cardinality(v_ok) = 0 THEN
    RETURN;
  END IF;

  INSERT INTO portal.ledger_purge_authorization (txid, ledger_name, purge_id)
  VALUES (v_txid, 'wf.run_history', NULL)
  ON CONFLICT DO NOTHING;

  FOREACH v_id IN ARRAY v_ok LOOP
    SELECT wi.status, wi.workflow_version_id INTO v_status, v_version
    FROM wf.workflow_instance wi WHERE wi.id = v_id;
    SELECT count(*) INTO v_nodes FROM wf.node_execution ne WHERE ne.workflow_instance_id = v_id;
    SELECT r.policy_obj_id INTO v_policy FROM wf.fn_run_retention(v_id) r;

    DELETE FROM wf.loop_state ls
    WHERE ls.workflow_instance_id = v_id
       OR ls.scope_node_execution_id IN (SELECT ne.id FROM wf.node_execution ne WHERE ne.workflow_instance_id = v_id);
    UPDATE wf.node_execution ne SET parent_node_execution_id = NULL
    WHERE ne.workflow_instance_id = v_id AND ne.parent_node_execution_id IS NOT NULL;
    DELETE FROM wf.workflow_instance wi WHERE wi.id = v_id;

    DELETE FROM wf.run_history h WHERE h.workflow_instance_id = v_id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;

    INSERT INTO wf.run_history (
      change_kind, workflow_instance_id, workflow_version_id, status_before, detail, actor_user_id
    ) VALUES (
      'run.purge', v_id, v_version, v_status,
      jsonb_strip_nulls(jsonb_build_object(
        'policy_obj_id', v_policy,
        'node_executions', v_nodes,
        'history_rows_removed', v_rows,
        'reason', p_reason
      )),
      NULLIF(current_setting('goliath.actor_user_id', true), '')::integer
    );

    workflow_instance_id := v_id; purged := true; reason := p_reason;
    RETURN NEXT;
  END LOOP;

  DELETE FROM portal.ledger_purge_authorization a
  WHERE a.txid = v_txid AND a.ledger_name = 'wf.run_history';
END;
$$;

REVOKE EXECUTE ON FUNCTION wf.sp_purge_run_history(bigint[], text, boolean) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION wf.fn_run_history_capture() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION wf.fn_run_delete_guard() FROM PUBLIC;

COMMIT;
