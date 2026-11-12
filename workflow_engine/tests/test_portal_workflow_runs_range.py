"""Workflow runs time range (portal.sp_list_recent_instances / sp_session_list_recent_instances)."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    if env.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    return env


def _psql(sql: str, env: dict[str, str]) -> str:
    proc = subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


@pytest.fixture(scope="module")
def runs_env() -> tuple[dict[str, str], str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    def_name = f"runs_range_test_{uuid.uuid4().hex[:10]}"
    _psql(
        f"""
        WITH d AS (
          INSERT INTO wf.workflow_def(name) VALUES ('{def_name}') RETURNING id
        ), v AS (
          INSERT INTO wf.workflow_version(workflow_def_id, version_major, version_minor)
          SELECT id, 1, 0 FROM d RETURNING id
        )
        INSERT INTO wf.workflow_instance(workflow_version_id, status, started_at_utc, completed_at_utc)
        SELECT v.id, x.status, x.started, x.completed
        FROM v, (VALUES
          ('COMPLETED', now() - interval '2 hours', now() - interval '1 hour'),
          ('COMPLETED', now() - interval '10 days', now() - interval '10 days'),
          ('COMPLETED', now() - interval '60 days', now() - interval '60 days'),
          ('CREATED', NULL::timestamptz, NULL::timestamptz)
        ) AS x(status, started, completed);
        """,
        env,
    )
    return env, def_name


def _count(env: dict[str, str], def_name: str, hours_sql: str, limit: int = 500) -> int:
    return int(
        _psql(
            "SELECT count(*) FROM portal.sp_list_recent_instances("
            f"{hours_sql}, {limit}) WHERE workflow_def_name = '{def_name}'",
            env,
        )
    )


def test_bounded_ranges_exclude_older_runs(runs_env: tuple[dict[str, str], str]) -> None:
    env, def_name = runs_env
    assert _count(env, def_name, "24") == 1
    assert _count(env, def_name, "168") == 1
    assert _count(env, def_name, "720") == 2


def test_null_or_nonpositive_hours_lists_all_runs(runs_env: tuple[dict[str, str], str]) -> None:
    env, def_name = runs_env
    assert _count(env, def_name, "NULL") == 4
    assert _count(env, def_name, "0") == 4


def test_all_runs_ordered_newest_first_with_unstarted_last(
    runs_env: tuple[dict[str, str], str],
) -> None:
    env, def_name = runs_env
    out = _psql(
        "SELECT string_agg(status || ':' || (started_at_utc IS NULL)::text, ',') FROM ("
        "SELECT status, started_at_utc FROM portal.sp_list_recent_instances(NULL, 500) "
        f"WHERE workflow_def_name = '{def_name}') t",
        env,
    )
    assert out.split(",")[-1] == "CREATED:true"


def test_session_wrapper_keeps_signature_and_portal_execute(
    runs_env: tuple[dict[str, str], str],
) -> None:
    env, _ = runs_env
    assert (
        _psql(
            "SELECT has_function_privilege('goliath_portal', "
            "'portal.sp_session_list_recent_instances(text,integer,integer)', 'EXECUTE')",
            env,
        )
        == "t"
    )
    with pytest.raises(RuntimeError, match="session denied"):
        _psql("SELECT * FROM portal.sp_session_list_recent_instances('', NULL, 100)", env)


def test_started_at_index_exists(runs_env: tuple[dict[str, str], str]) -> None:
    env, _ = runs_env
    assert _psql("SELECT to_regclass('wf.ix_wi_started_at') IS NOT NULL", env) == "t"
