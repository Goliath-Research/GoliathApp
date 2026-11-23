"""Every GoliathApp timestamp is stored as UTC, whatever the session time zone.

All *_at_utc / *AtUtc columns are timestamptz. Writing (now() AT TIME ZONE 'utc') into them stores an
instant shifted by the session's UTC offset; these tests run in sessions east and west of UTC and check
that defaults, the workflow engine and the migration of older databases all store the true instant.
"""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, LiteralString

import psycopg
import pytest
from psycopg import sql

from tests.pg_require_ci import require_postgres_reachable, require_psql

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
MIGRATION = SQL_PG / "platform_utc_timestamps.sql"

# West and east of UTC, including a half-hour offset and the largest positive offset.
NON_UTC_ZONES = ("America/New_York", "Asia/Kolkata", "Pacific/Kiritimati")
TOLERANCE_SECONDS = 120

_LOCAL_WALL_CLOCK = re.compile(
    r"(now|clock_timestamp|statement_timestamp|transaction_timestamp)\(\)\s+AT\s+TIME\s+ZONE\s+'utc'", re.I
)
_TO_CHAR_UTC = re.compile(r"to_char\(\s*now\(\)\s+AT\s+TIME\s+ZONE\s+'utc'", re.I)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    return env


@pytest.fixture(scope="module")
def utc_db() -> str:
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


def _one(conn: psycopg.Connection, query: LiteralString, params: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return tuple(row)


def _drift_seconds(conn: psycopg.Connection, value_sql: sql.Composable) -> float:
    query = sql.SQL("SELECT abs(extract(epoch FROM ({}) - now()))::float8").format(value_sql)
    row = conn.execute(query).fetchone()
    assert row is not None and row[0] is not None
    return float(row[0])


def test_sql_sources_never_store_utc_wall_clock() -> None:
    offenders = []
    for path in sorted(SQL_PG.rglob("*.sql")):
        if path == MIGRATION:  # documents the legacy pattern it rewrites
            continue
        text = _TO_CHAR_UTC.sub("", path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(text.splitlines(), 1):
            if _LOCAL_WALL_CLOCK.search(line) and not line.lstrip().startswith("--"):
                offenders.append(f"{path.relative_to(SQL_PG)}:{lineno}: {line.strip()}")
    assert not offenders, "use now() for timestamptz values:\n" + "\n".join(offenders)


def test_deployed_schema_has_no_utc_wall_clock_defaults_or_writes(utc_db: str) -> None:
    with psycopg.connect(utc_db) as conn:
        rows = conn.execute("SELECT object_kind, object_name, detail FROM portal.fn_utc_timestamp_violations()").fetchall()
    assert rows == []


def test_all_app_timestamp_columns_are_timestamptz(utc_db: str) -> None:
    with psycopg.connect(utc_db) as conn:
        rows = conn.execute(
            """
            SELECT table_schema, table_name, column_name
            FROM information_schema.columns
            WHERE table_schema IN ('wf', 'portal', 'cfg', 'inv', 'Meta', 'RBAC', 'Contract', 'Onboarding')
              AND data_type = 'timestamp without time zone'
            """
        ).fetchall()
    assert rows == []


@pytest.mark.parametrize("zone", NON_UTC_ZONES)
def test_every_timestamp_default_is_the_current_instant_in_a_non_utc_session(utc_db: str, zone: str) -> None:
    with psycopg.connect(utc_db) as conn:
        conn.execute(sql.SQL("SET TIME ZONE {}").format(sql.Literal(zone)))
        defaults = conn.execute(
            """
            SELECT format('%I.%I.%I', n.nspname, c.relname, a.attname), pg_get_expr(d.adbin, d.adrelid)
            FROM pg_attrdef d
            JOIN pg_class c ON c.oid = d.adrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
            WHERE n.nspname IN ('wf', 'portal', 'cfg', 'inv', 'Meta', 'RBAC', 'Contract', 'Onboarding')
              AND c.relkind IN ('r', 'p')
              AND a.atttypid = 'timestamptz'::regtype
              AND pg_get_expr(d.adbin, d.adrelid) ~* '(now|clock_timestamp|statement_timestamp|transaction_timestamp|current_timestamp)'
            """
        ).fetchall()
        assert len(defaults) > 50
        late = []
        for column, expr in defaults:
            # The expression is a catalog default read back from pg_attrdef, not user input.
            drift = _drift_seconds(conn, sql.SQL(expr))  # pyrefly: ignore
            if drift > TOLERANCE_SECONDS:
                late.append(f"{column} = {expr} is off by {drift:.0f}s")
        assert not late, "\n".join(late)


@pytest.mark.parametrize("zone", NON_UTC_ZONES)
def test_workflow_engine_stamps_true_instants_in_a_non_utc_session(utc_db: str, zone: str) -> None:
    with psycopg.connect(utc_db, autocommit=True) as conn:
        conn.execute(sql.SQL("SET TIME ZONE {}").format(sql.Literal(zone)))
        name = f"UtcFlow_{uuid.uuid4().hex[:8]}"
        def_id = int(_one(conn, "INSERT INTO wf.workflow_def (name) VALUES (%s) RETURNING id", (name,))[0])
        version_id = int(
            _one(conn, "INSERT INTO wf.workflow_version (workflow_def_id) VALUES (%s) RETURNING id", (def_id,))[0]
        )
        action = conn.execute("SELECT id FROM wf.workflow_action WHERE action_name = 'UtcTestAction'").fetchone()
        if action is None:
            action = _one(
                conn,
                "INSERT INTO wf.workflow_action (action_name, capability) VALUES ('UtcTestAction', 'utc-cap') RETURNING id",
            )
        node_id = int(
            _one(
                conn,
                "INSERT INTO wf.workflow_node (workflow_version_id, node_type, node_key, workflow_action_id) "
                "VALUES (%s, 'ACTION', 'step', %s) RETURNING id",
                (version_id, action[0]),
            )[0]
        )
        conn.execute("UPDATE wf.workflow_version SET root_node_id = %s WHERE id = %s", (node_id, version_id))

        inst = int(_one(conn, "SELECT id FROM wf.wf_repo_create_workflow_instance(%s, '{}'::jsonb)", (version_id,))[0])
        conn.execute("CALL wf.sp_start_workflow_instance(%s)", (inst,))

        stamped = conn.execute(
            """
            SELECT 'workflow_instance.started_at_utc', started_at_utc FROM wf.workflow_instance WHERE id = %s
            UNION ALL SELECT 'node_execution.' || col, val
              FROM wf.node_execution ne,
                   LATERAL (VALUES ('available_at_utc', ne.available_at_utc), ('started_at_utc', ne.started_at_utc)) v(col, val)
             WHERE ne.workflow_instance_id = %s
            """,
            (inst, inst),
        ).fetchall()
        now = _one(conn, "SELECT now()")[0]
        values = [(label, ts) for label, ts in stamped if ts is not None]
        assert any(label == "workflow_instance.started_at_utc" for label, _ in values), stamped
        for label, ts in values:
            assert abs((ts - now).total_seconds()) <= TOLERANCE_SECONDS, f"{label} = {ts} in {zone} (now {now})"


def test_migration_fixes_legacy_wall_clock_defaults(utc_db: str) -> None:
    table = f"utc_legacy_{uuid.uuid4().hex[:8]}"
    env = _env()
    with psycopg.connect(utc_db, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "CREATE TABLE wf.{} (id int, created_at_utc timestamptz NOT NULL DEFAULT (now() AT TIME ZONE 'utc'))"
            ).format(sql.Identifier(table))
        )
        try:
            subprocess.run(
                ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(MIGRATION)], env=env, check=True, capture_output=True
            )
            expr = _one(
                conn,
                "SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d "
                "JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
                "WHERE d.adrelid = %s::regclass AND a.attname = 'created_at_utc'",
                (f"wf.{table}",),
            )[0]
            assert expr == "now()"
            conn.execute("SET TIME ZONE 'America/Los_Angeles'")
            conn.execute(sql.SQL("INSERT INTO wf.{} (id) VALUES (1)").format(sql.Identifier(table)))
            drift = _drift_seconds(conn, sql.SQL("SELECT created_at_utc FROM wf.{}").format(sql.Identifier(table)))
            assert drift <= TOLERANCE_SECONDS
        finally:
            conn.execute(sql.SQL("DROP TABLE IF EXISTS wf.{}").format(sql.Identifier(table)))


def test_legacy_operator_view_overloads_are_dropped_on_upgrade(utc_db: str) -> None:
    """Databases from before #80 kept 8- and 4-argument overloads that stamped UTC wall clocks."""
    env = _env()
    with psycopg.connect(utc_db, autocommit=True) as conn:
        conn.execute(
            "CREATE OR REPLACE FUNCTION portal.sp_session_upsert_operator_view("
            "text, bigint, text, text, text, text, text, jsonb) RETURNS bigint LANGUAGE sql AS 'SELECT 1::bigint'"
        )
        conn.execute(
            "CREATE OR REPLACE FUNCTION portal.sp_session_upsert_operator_dashboard("
            "text, bigint, text, text) RETURNS bigint LANGUAGE sql AS 'SELECT 1::bigint'"
        )
        subprocess.run(
            ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(SQL_PG / "portal_operator_views_api.sql")],
            env=env,
            check=True,
            capture_output=True,
        )
        rows = conn.execute(
            "SELECT p.proname, p.pronargs FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'portal' AND p.proname IN "
            "('sp_session_upsert_operator_view', 'sp_session_upsert_operator_dashboard') ORDER BY 1"
        ).fetchall()
    assert rows == [("sp_session_upsert_operator_dashboard", 6), ("sp_session_upsert_operator_view", 9)]
