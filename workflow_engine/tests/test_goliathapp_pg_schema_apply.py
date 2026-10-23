"""Apply GoliathApp PostgreSQL schema twice (idempotent) and smoke-test organization APIs."""

from __future__ import annotations

import os
import subprocess
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
def pg_schema_applied() -> dict[str, str]:
    if not shutil_which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    if not env.get("PGPASSWORD") and env.get("PGHOST", "localhost") in ("localhost", "127.0.0.1"):
        env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "methyl"))
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable for schema apply test")
    for _ in range(2):
        subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    return env


def shutil_which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


def test_organization_lifecycle(pg_schema_applied: dict[str, str]) -> None:
    env = pg_schema_applied
    import uuid

    email = f"org-admin-{uuid.uuid4().hex[:8]}@test"
    user_id = _psql(
        f"""
        INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
        VALUES ('Org Admin', '{email}', 1)
        RETURNING "ID"
        """,
        env,
    )
    row = _psql(
        f"SELECT * FROM portal.sp_organization_create('Test Org {user_id}')",
        env,
    )
    org_id, scope_id = row.split("|")
    assert int(org_id) > 0
    assert int(scope_id) > 0
    _psql(
        f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {user_id})",
        env,
    )
    members = _psql(
        f"SELECT count(*) FROM portal.sp_list_organization_members({org_id})",
        env,
    )
    assert int(members) >= 1


def test_nav_register_node(pg_schema_applied: dict[str, str]) -> None:
    env = pg_schema_applied
    node_id = _psql(
        "SELECT node_id FROM portal.sp_nav_register_node(NULL, 'Home', 1::smallint)",
        env,
    )
    assert int(node_id) > 0
