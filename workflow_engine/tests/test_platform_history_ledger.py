"""Platform history ledger: append-only, hash-chained audit and event tables (H1)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, LiteralString

import psycopg
import pytest

from tests.pg_require_ci import require_postgres_reachable, require_psql

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
LEDGER_SQL = SQL_PG / "platform_history_ledger.sql"

EXPECTED_LEDGERS = {
    "onboarding.audit_log",
    "portal.external_identity_link_audit",
    "portal.god_architect_audit",
    "portal.model_authoring_audit",
    "portal.record_editor_audit",
    "portal.security_admin_audit",
    "portal.session_active_role_audit",
    "wf.event",
    "wf.event_delivery",
}


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    return env


def _conninfo(env: dict[str, str]) -> str:
    return (
        f"host={env['PGHOST']} port={env['PGPORT']} dbname={env['PGDATABASE']} "
        f"user={env['PGUSER']} password={env['PGPASSWORD']}"
    )


@pytest.fixture(scope="module")
def ledger_db() -> str:
    require_psql()
    env = _env()

    def _probe() -> None:
        try:
            with psycopg.connect(_conninfo(env), connect_timeout=5) as conn:
                conn.execute("SELECT 1")
        except psycopg.Error as exc:
            raise RuntimeError(str(exc)) from exc

    require_postgres_reachable(_probe)
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True, capture_output=True)
    return _conninfo(env)


def _problems(conn: psycopg.Connection, ledger: str) -> list[tuple[int, str]]:
    return [(int(r[0]), str(r[1])) for r in conn.execute(
        "SELECT ledger_seq, problem FROM portal.fn_ledger_verify(%s)", (ledger,)
    ).fetchall()]


def _one(conn: psycopg.Connection, sql: LiteralString, params: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return tuple(row)


def _audit(conn: psycopg.Connection, action: str) -> int:
    conn.execute(
        "SELECT portal.fn_record_editor_audit(1, 1, NULL, 'ledger.test', %s, 'k', '{}'::jsonb)",
        (action,),
    )
    row = conn.execute(
        "SELECT ledger_seq FROM portal.record_editor_audit WHERE action_code = %s "
        "ORDER BY ledger_seq DESC LIMIT 1",
        (action,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_registry_lists_platform_ledgers_and_all_verify(ledger_db: str) -> None:
    with psycopg.connect(ledger_db, autocommit=True) as conn:
        names = {r[0] for r in conn.execute("SELECT ledger_name FROM portal.ledger_registry").fetchall()}
        assert EXPECTED_LEDGERS <= names
        assert conn.execute("SELECT * FROM portal.fn_ledger_verify_all()").fetchall() == []


def test_insert_is_chained(ledger_db: str) -> None:
    with psycopg.connect(ledger_db, autocommit=True) as conn:
        first = _audit(conn, "ledger.chain.a")
        second = _audit(conn, "ledger.chain.b")
        assert second == first + 1
        prev, row_hash, txid = _one(
            conn,
            "SELECT prev_hash, row_hash, txid FROM portal.record_editor_audit WHERE ledger_seq = %s",
            (second,),
        )
        first_hash = _one(
            conn, "SELECT row_hash FROM portal.record_editor_audit WHERE ledger_seq = %s", (first,)
        )[0]
        assert prev == first_hash
        assert row_hash is not None and len(row_hash) == 32
        assert txid is not None
        assert _problems(conn, "portal.record_editor_audit") == []


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE portal.record_editor_audit SET action_code = 'x'",
        "DELETE FROM portal.record_editor_audit",
        "TRUNCATE portal.record_editor_audit",
        "UPDATE wf.event SET source = 'x'",
        "DELETE FROM portal.god_architect_audit",
    ],
)
def test_update_delete_truncate_refused(ledger_db: str, statement: LiteralString) -> None:
    with psycopg.connect(ledger_db, autocommit=True) as conn:
        _audit(conn, "ledger.refuse")
        conn.execute(
            "SELECT portal.fn_session_god_architect_audit(1, 1, 'ledger.refuse', '{}'::jsonb)"
        )
        conn.execute(
            "INSERT INTO wf.event_type (name) VALUES ('ledger.test.refuse') ON CONFLICT DO NOTHING"
        )
        conn.execute(
            "SELECT * FROM wf.sp_ingest_event('ledger.test.refuse', 'ledger-test', 'refuse-1', '{}'::jsonb)"
        )
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(statement)
        assert "append-only" in str(exc.value)


def test_edit_outside_platform_is_detected(ledger_db: str) -> None:
    with psycopg.connect(ledger_db) as conn:
        seq = _audit(conn, "ledger.tamper")
        conn.execute("ALTER TABLE portal.record_editor_audit DISABLE TRIGGER trg_ledger_guard")
        conn.execute(
            "UPDATE portal.record_editor_audit SET payload = '{\"forged\": true}' WHERE ledger_seq = %s",
            (seq,),
        )
        assert (seq, "hash_mismatch") in _problems(conn, "portal.record_editor_audit")
        conn.rollback()


def test_delete_outside_purge_is_detected(ledger_db: str) -> None:
    with psycopg.connect(ledger_db) as conn:
        seq = _audit(conn, "ledger.gap")
        _audit(conn, "ledger.gap.after")
        conn.execute("ALTER TABLE portal.record_editor_audit DISABLE TRIGGER trg_ledger_guard")
        conn.execute("DELETE FROM portal.record_editor_audit WHERE ledger_seq = %s", (seq,))
        assert (seq, "missing_seq") in _problems(conn, "portal.record_editor_audit")
        conn.rollback()


def test_authorized_purge_leaves_tombstone_and_chain_verifies(ledger_db: str) -> None:
    with psycopg.connect(ledger_db) as conn:
        seq = _audit(conn, "ledger.purge")
        _audit(conn, "ledger.purge.after")
        conn.execute(
            "INSERT INTO portal.ledger_purge_authorization (txid, ledger_name) "
            "VALUES (portal.fn_ledger_current_txid(), 'portal.record_editor_audit')"
        )
        conn.execute("DELETE FROM portal.record_editor_audit WHERE ledger_seq = %s", (seq,))
        tomb = _one(
            conn,
            "SELECT count(*) FROM portal.ledger_tombstone WHERE ledger_name = 'portal.record_editor_audit' "
            "AND ledger_seq = %s",
            (seq,),
        )[0]
        assert tomb == 1
        assert _problems(conn, "portal.record_editor_audit") == []
        conn.rollback()


def test_verify_independent_of_session_timezone(ledger_db: str) -> None:
    with psycopg.connect(ledger_db, autocommit=True) as conn:
        _audit(conn, "ledger.tz")
        conn.execute("SET TimeZone = 'America/New_York'")
        conn.execute("SET bytea_output = 'escape'")
        assert conn.execute("SELECT * FROM portal.fn_ledger_verify_all()").fetchall() == []


def test_reapply_keeps_chain(ledger_db: str) -> None:
    env = _env()
    with psycopg.connect(ledger_db, autocommit=True) as conn:
        _audit(conn, "ledger.reapply")
        before = conn.execute("SELECT * FROM portal.fn_ledger_checkpoint()").fetchall()
    subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(LEDGER_SQL)],
        env=env, check=True, capture_output=True,
    )
    with psycopg.connect(ledger_db, autocommit=True) as conn:
        after = conn.execute("SELECT * FROM portal.fn_ledger_checkpoint()").fetchall()
        assert [r[:3] for r in before] == [r[:3] for r in after]
        assert conn.execute("SELECT * FROM portal.fn_ledger_verify_all()").fetchall() == []


def test_existing_rows_are_backfilled_on_first_registration(ledger_db: str) -> None:
    with psycopg.connect(ledger_db) as conn:
        conn.execute("CREATE TABLE portal._ledger_backfill_probe (id int PRIMARY KEY, v text)")
        conn.execute("INSERT INTO portal._ledger_backfill_probe VALUES (2, 'b'), (1, 'a'), (3, 'c')")
        conn.execute(
            "SELECT portal.sp_ledger_register('test.backfill', 'portal._ledger_backfill_probe', 'id')"
        )
        rows = conn.execute(
            "SELECT id, ledger_seq FROM portal._ledger_backfill_probe ORDER BY id"
        ).fetchall()
        assert rows == [(1, 1), (2, 2), (3, 3)]
        conn.execute("INSERT INTO portal._ledger_backfill_probe (id, v) VALUES (4, 'd')")
        assert _problems(conn, "test.backfill") == []
        conn.rollback()


def test_duplicate_event_does_not_consume_a_sequence_number(ledger_db: str) -> None:
    with psycopg.connect(ledger_db, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO wf.event_type (name) VALUES ('ledger.test.dup') ON CONFLICT DO NOTHING"
        )
        for _ in range(2):
            conn.execute(
                "SELECT * FROM wf.sp_ingest_event('ledger.test.dup', 'ledger-test', 'dup-key-1', '{}'::jsonb)"
            )
        count = _one(
            conn,
            "SELECT count(*) FROM wf.event WHERE source = 'ledger-test' AND idempotency_key = 'dup-key-1'",
        )[0]
        assert count == 1
        assert _problems(conn, "wf.event") == []


def test_ledger_functions_are_not_executable_by_portal_role(ledger_db: str) -> None:
    with psycopg.connect(ledger_db, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'portal' AND p.proname LIKE '%%ledger%%' "
            "AND has_function_privilege('goliath_portal', p.oid, 'EXECUTE')"
        ).fetchall()
        assert rows == []


def test_checkpoint_time_is_absolute_in_any_session_timezone(ledger_db: str) -> None:
    with psycopg.connect(ledger_db, autocommit=True) as conn:
        conn.execute("SET TIME ZONE 'America/New_York'")
        skew = _one(conn, "SELECT max(abs(extract(epoch FROM taken_at_utc - now()))) FROM portal.fn_ledger_checkpoint()")[0]
        assert skew is not None and float(skew) < 60
