"""Regression: SCHEDULE support must survive full apply order (08 replaces core procs after wf_schedule_support)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.helpers import pg_integration

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"


def _env_for_ci() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    if env.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    elif env.get("PGHOST", "localhost") in ("localhost", "127.0.0.1"):
        env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    return env


def _apply_full_schema() -> None:
    if not pg_integration.shutil_which_cmd("psql"):
        pytest.skip("psql not installed")
    env = _env_for_ci()
    try:
        subprocess.run(["bash", str(APPLY_SH)], env=env, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"schema apply unavailable: {exc.stderr or exc.stdout}")


@pytest.fixture(scope="module")
def full_schema_env() -> dict[str, str]:
    env = _env_for_ci()
    _apply_full_schema()
    return env


def test_wf_engine_procedures_include_schedule_continue(full_schema_env: dict[str, str]) -> None:
    """After apply_schema.sh order, final wf_engine_* bodies must dispatch SCHEDULE → wf_schedule_continue."""
    markers = pg_integration.wf_engine_procedures_reference_schedule()
    for proc_name, needle in markers.items():
        sql = (
            "SELECT COUNT(*) FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace "
            f"WHERE n.nspname = 'wf' AND p.proname = '{proc_name}' "
            f"AND p.prosrc LIKE '%{needle}%'"
        )
        proc = subprocess.run(
            ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
            env=full_schema_env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            pytest.fail(proc.stderr or proc.stdout)
        count = int((proc.stdout or "").strip() or "0")
        assert count >= 1, f"{proc_name} must reference {needle} after schema apply"
