"""Workflow run history and retention (H3): runs are kept, and removed only under a retention policy."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Any, LiteralString

import psycopg
import pytest

from tests.pg_require_ci import require_postgres_reachable, require_psql

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    return env


@pytest.fixture(scope="module")
def run_db() -> str:
    require_psql()
    env = _env()
    conninfo = (
        f"host={env['PGHOST']} port={env['PGPORT']} dbname={env['PGDATABASE']} "
        f"user={env['PGUSER']} password={env['PGPASSWORD']}"
    )

    def _probe() -> None:
        try:
            with psycopg.connect(conninfo, connect_timeout=5) as conn:
                conn.execute("SELECT 1")
        except psycopg.Error as exc:
            raise RuntimeError(str(exc)) from exc

    require_postgres_reachable(_probe)
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True, capture_output=True)
    return conninfo


def _one(conn: psycopg.Connection, sql: LiteralString, params: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return tuple(row)


def _workflow(conn: psycopg.Connection) -> tuple[str, int, int]:
    """A throwaway workflow definition with one ACTION node. Returns (name, version_id, node_id)."""
    name = f"RunHistoryFlow_{uuid.uuid4().hex[:8]}"
    def_id = int(_one(conn, "INSERT INTO wf.workflow_def (name) VALUES (%s) RETURNING id", (name,))[0])
    version_id = int(_one(conn, "INSERT INTO wf.workflow_version (workflow_def_id) VALUES (%s) RETURNING id", (def_id,))[0])
    action = conn.execute("SELECT id FROM wf.workflow_action WHERE action_name = 'RunHistoryTestAction'").fetchone()
    if action is None:
        action = _one(
            conn,
            "INSERT INTO wf.workflow_action (action_name, capability) VALUES ('RunHistoryTestAction', 'test-cap') RETURNING id",
        )
    node_id = int(_one(
        conn,
        "INSERT INTO wf.workflow_node (workflow_version_id, node_type, node_key, workflow_action_id) "
        "VALUES (%s, 'ACTION', 'step', %s) RETURNING id",
        (version_id, action[0]),
    )[0])
    conn.execute("UPDATE wf.workflow_version SET root_node_id = %s WHERE id = %s", (node_id, version_id))
    return name, version_id, node_id


def _workers(conn: psycopg.Connection) -> tuple[int, int]:
    cluster = conn.execute("SELECT id FROM wf.cluster WHERE cluster_key = 'runhistory'").fetchone()
    if cluster is None:
        cluster = _one(conn, "INSERT INTO wf.cluster (cluster_key, name) VALUES ('runhistory', 'Run history') RETURNING id")
    ids = []
    for key in ("rh-w1", "rh-w2"):
        row = conn.execute(
            "SELECT id FROM wf.worker WHERE cluster_id = %s AND external_worker_key = %s", (cluster[0], key)
        ).fetchone()
        if row is None:
            row = _one(
                conn, "INSERT INTO wf.worker (cluster_id, external_worker_key) VALUES (%s, %s) RETURNING id", (cluster[0], key)
            )
        ids.append(int(row[0]))
    return ids[0], ids[1]


def _run(conn: psycopg.Connection, version_id: int, node_id: int, *, finished_days_ago: int | None = None) -> tuple[int, int]:
    inst = int(_one(conn, "INSERT INTO wf.workflow_instance (workflow_version_id) VALUES (%s) RETURNING id", (version_id,))[0])
    ne = int(_one(
        conn, "INSERT INTO wf.node_execution (workflow_instance_id, workflow_node_id) VALUES (%s, %s) RETURNING id",
        (inst, node_id),
    )[0])
    if finished_days_ago is not None:
        conn.execute(
            "UPDATE wf.workflow_instance SET status = 'COMPLETED', "
            "started_at_utc = now() - make_interval(days => %s), completed_at_utc = now() - make_interval(days => %s) "
            "WHERE id = %s",
            (finished_days_ago, finished_days_ago, inst),
        )
    return inst, ne


def _policy(conn: psycopg.Connection, workflow_name: str | None, days: int, hold: bool = False) -> int:
    return int(_one(
        conn,
        """SELECT "Meta".sp_obj_insert(
             (SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'platform/RetentionPolicy'),
             jsonb_strip_nulls(jsonb_build_object(
               'Label', 'Test policy', 'RecordKind', 'wf.run', 'WorkflowName', %s::text,
               'RetentionDays', %s::int, 'LegalHold', %s::boolean)))""",
        (workflow_name, days, hold),
    )[0])


def _kinds(conn: psycopg.Connection, inst: int) -> list[str]:
    return [str(r[0]) for r in conn.execute(
        "SELECT change_kind FROM wf.run_history WHERE workflow_instance_id = %s ORDER BY history_id", (inst,)
    ).fetchall()]


def _purge(conn: psycopg.Connection, inst: int) -> tuple[bool, str | None]:
    row = _one(conn, "SELECT purged, reason FROM wf.sp_purge_run_history(ARRAY[%s]::bigint[], 'test')", (inst,))
    return bool(row[0]), row[1]


def _verify(conn: psycopg.Connection) -> list[tuple[Any, ...]]:
    return conn.execute("SELECT * FROM portal.fn_ledger_verify('wf.run_history')").fetchall()


def test_run_history_is_a_registered_ledger(run_db: str) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        assert _one(conn, "SELECT count(*) FROM portal.ledger_registry WHERE ledger_name = 'wf.run_history'")[0] == 1
        assert _verify(conn) == []


def test_transitions_and_worker_leases_are_recorded(run_db: str) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        _, version_id, node_id = _workflow(conn)
        w1, w2 = _workers(conn)
        inst, ne = _run(conn, version_id, node_id)
        conn.execute("UPDATE wf.workflow_instance SET status = 'RUNNING' WHERE id = %s", (inst,))
        conn.execute("UPDATE wf.node_execution SET status = 'RUNNING' WHERE id = %s", (ne,))
        conn.execute(
            "INSERT INTO wf.task_lease (node_execution_id, worker_id, lease_expires_at_utc) VALUES (%s, %s, now() + interval '1 minute')",
            (ne, w1),
        )
        conn.execute("UPDATE wf.task_lease SET heartbeat_at_utc = now() WHERE node_execution_id = %s", (ne,))
        conn.execute("UPDATE wf.task_lease SET worker_id = %s WHERE node_execution_id = %s", (w2, ne))
        conn.execute("DELETE FROM wf.task_lease WHERE node_execution_id = %s", (ne,))
        conn.execute(
            "UPDATE wf.node_execution SET status = 'SUCCEEDED', completed_by_worker_id = %s, output_json = '{\"n\": 1}'::jsonb WHERE id = %s",
            (w2, ne),
        )
        conn.execute("UPDATE wf.workflow_instance SET status = 'COMPLETED' WHERE id = %s", (inst,))

        assert _kinds(conn, inst) == [
            "instance.create", "node.create", "instance.status", "node.status",
            "lease.acquire", "lease.transfer", "lease.release", "node.status", "instance.status",
        ]
        workers = conn.execute(
            "SELECT change_kind, worker_id FROM wf.run_history WHERE workflow_instance_id = %s AND worker_id IS NOT NULL ORDER BY history_id",
            (inst,),
        ).fetchall()
        assert [(r[0], r[1]) for r in workers] == [
            ("lease.acquire", w1), ("lease.transfer", w2), ("lease.release", w2), ("node.status", w2),
        ]
        final = _one(
            conn,
            "SELECT status_before, status_after, detail FROM wf.run_history "
            "WHERE workflow_instance_id = %s AND change_kind = 'node.status' ORDER BY history_id DESC LIMIT 1",
            (inst,),
        )
        assert final[0] == "RUNNING" and final[1] == "SUCCEEDED" and final[2]["output"] == {"n": 1}
        assert _verify(conn) == []


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM wf.workflow_instance WHERE id = %s",
        "DELETE FROM wf.node_execution WHERE workflow_instance_id = %s",
    ],
)
def test_runs_cannot_be_deleted_directly(run_db: str, statement: LiteralString) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        _, version_id, node_id = _workflow(conn)
        inst, _ = _run(conn, version_id, node_id)
        with pytest.raises(psycopg.Error, match="run history"):
            conn.execute(statement, (inst,))
        with pytest.raises(psycopg.Error):
            conn.execute("UPDATE wf.run_history SET status_after = 'X' WHERE workflow_instance_id = %s", (inst,))


def test_truncate_is_refused(run_db: str) -> None:
    with psycopg.connect(run_db) as conn:
        with pytest.raises(psycopg.Error, match="run history"):
            conn.execute("TRUNCATE wf.workflow_instance CASCADE")
        conn.rollback()


def test_without_policy_runs_are_kept_forever(run_db: str) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        _, version_id, node_id = _workflow(conn)
        inst, _ = _run(conn, version_id, node_id, finished_days_ago=3650)
        purged, reason = _purge(conn, inst)
        assert not purged and reason is not None and "no retention policy" in reason
        assert _one(conn, "SELECT count(*) FROM wf.workflow_instance WHERE id = %s", (inst,))[0] == 1


def test_purge_after_retention_leaves_tombstones_and_a_purge_record(run_db: str) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        name, version_id, node_id = _workflow(conn)
        policy = _policy(conn, name, 30)
        recent, _ = _run(conn, version_id, node_id, finished_days_ago=1)
        old, _ = _run(conn, version_id, node_id, finished_days_ago=40)
        rows_before = len(_kinds(conn, old))

        purged, reason = _purge(conn, recent)
        assert not purged and reason is not None and "30 days" in reason
        tomb_before = int(_one(conn, "SELECT count(*) FROM portal.ledger_tombstone WHERE ledger_name = 'wf.run_history'")[0])
        purged, _ = _purge(conn, old)
        assert purged

        assert _one(conn, "SELECT count(*) FROM wf.workflow_instance WHERE id = %s", (old,))[0] == 0
        assert _kinds(conn, old) == ["run.purge"]
        detail = _one(
            conn, "SELECT detail FROM wf.run_history WHERE workflow_instance_id = %s AND change_kind = 'run.purge'", (old,)
        )[0]
        assert detail["policy_obj_id"] == policy and detail["history_rows_removed"] == rows_before
        tomb_after = int(_one(conn, "SELECT count(*) FROM portal.ledger_tombstone WHERE ledger_name = 'wf.run_history'")[0])
        assert tomb_after - tomb_before == rows_before
        assert _verify(conn) == []
        assert _one(
            conn, "SELECT count(*) FROM portal.ledger_purge_authorization WHERE ledger_name = 'wf.run_history'"
        )[0] == 0


def test_legal_hold_blocks_purge(run_db: str) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        name, version_id, node_id = _workflow(conn)
        _policy(conn, name, 0)
        _policy(conn, name, 0, hold=True)
        inst, _ = _run(conn, version_id, node_id, finished_days_ago=400)
        purged, reason = _purge(conn, inst)
        assert not purged and reason == "legal hold"


def test_unfinished_runs_are_kept_unless_policy_is_zero_days(run_db: str) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        name, version_id, node_id = _workflow(conn)
        _policy(conn, name, 1)
        inst, _ = _run(conn, version_id, node_id)
        purged, reason = _purge(conn, inst)
        assert not purged and reason == "run is not finished"


def test_delete_workflow_definition_no_longer_cascades_into_history(run_db: str) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        name, version_id, node_id = _workflow(conn)
        inst, _ = _run(conn, version_id, node_id, finished_days_ago=10)
        with pytest.raises(psycopg.Error, match="cannot be purged"):
            conn.execute("SELECT * FROM wf.sp_delete_workflow_def(NULL, %s, true)", (name,))
        assert _one(conn, "SELECT count(*) FROM wf.workflow_instance WHERE id = %s", (inst,))[0] == 1

        _policy(conn, name, 0)
        deleted = _one(conn, "SELECT deleted_instance_count FROM wf.sp_delete_workflow_def(NULL, %s, true)", (name,))[0]
        assert deleted == 1
        assert _kinds(conn, inst) == ["run.purge"]
        assert _verify(conn) == []


def test_retention_policy_is_a_god_architect_meta_class_with_purge_method(run_db: str) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        cls = int(_one(conn, """SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'platform/RetentionPolicy'""")[0])
        method = _one(
            conn, """SELECT "ImplKind", "ImplRef" FROM "Meta"."Methods" WHERE "ClassID" = %s AND "Name" = 'PurgeExpiredRuns'""",
            (cls,),
        )
        assert method == ("sql", "wf.sp_purge_run_history")
        # Session writes to platform classes other than security data need God Architect.
        assert _one(conn, "SELECT portal.fn_meta_platform_god_architect_class('platform/RetentionPolicy')")[0] is True
        assert _one(
            conn, "SELECT has_function_privilege('goliath_portal', 'wf.sp_purge_run_history(bigint[],text,boolean)', 'EXECUTE')"
        )[0] is False


def test_zero_day_purge_works_in_a_session_west_of_utc(run_db: str) -> None:
    with psycopg.connect(run_db, autocommit=True) as conn:
        conn.execute("SET TIME ZONE 'America/New_York'")
        name, version_id, node_id = _workflow(conn)
        _policy(conn, name, 0)
        inst, _ = _run(conn, version_id, node_id)
        # A pre-fix row written by a non-UTC session holds a UTC wall-clock value read as local time,
        # five hours in the future here; it must still purge on time.
        conn.execute(
            "UPDATE wf.workflow_instance SET started_at_utc = (now() AT TIME ZONE 'utc')::timestamptz WHERE id = %s",
            (inst,),
        )
        purged, reason = _purge(conn, inst)
        assert purged, reason
