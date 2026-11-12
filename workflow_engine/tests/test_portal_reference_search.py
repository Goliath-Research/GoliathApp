"""Reference picker search (portal.sp_session_search_references)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"

KINDS = [
    "action",
    "meta_method",
    "workflow_def",
    "workflow_version",
    "event_type",
    "cluster",
    "worker",
    "data_type",
    "meta_class",
    "study",
]


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
def ref_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    return env


@pytest.mark.parametrize("kind", KINDS)
def test_known_kinds_require_session(ref_env: dict[str, str], kind: str) -> None:
    with pytest.raises(RuntimeError, match="session denied"):
        _psql(f"SELECT * FROM portal.sp_session_search_references('', '{kind}', '', 10)", ref_env)


def test_unknown_kind_rejected(ref_env: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="unknown reference kind"):
        _psql("SELECT * FROM portal.sp_session_search_references('x', 'nope', '', 10)", ref_env)


def test_portal_role_can_execute(ref_env: dict[str, str]) -> None:
    assert (
        _psql(
            "SELECT has_function_privilege('goliath_portal', "
            "'portal.sp_session_search_references(text,text,text,integer)', 'EXECUTE')",
            ref_env,
        )
        == "t"
    )
