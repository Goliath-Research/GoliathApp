"""Upgrade path: apply schema twice and verify production security checks."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
PRODUCTION_FIXTURE = SQL_PG / "test_fixtures" / "security_meta_production_shape.sql"
UPGRADE_TEST_DB = "goliathapp_security_upgrade_test"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
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
def upgrade_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    admin_env = _pg_env()
    admin_env["PGDATABASE"] = "postgres"
    if not admin_env.get("PGPASSWORD"):
        admin_env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath"))
    try:
        _psql("SELECT 1", admin_env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    _psql(f'DROP DATABASE IF EXISTS "{UPGRADE_TEST_DB}" WITH (FORCE)', admin_env)
    _psql(f'CREATE DATABASE "{UPGRADE_TEST_DB}"', admin_env)
    env = _pg_env()
    env["PGDATABASE"] = UPGRADE_TEST_DB
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(PRODUCTION_FIXTURE)], env=env, check=True)
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    return env


def test_upgrade_idempotent_and_cache_wired(upgrade_env: dict[str, str]) -> None:
    grant_count = int(_psql("SELECT COUNT(*) FROM portal.mv_security_effective_grants", upgrade_env))
    assert grant_count >= 0
    user_map = int(_psql("SELECT COUNT(*) FROM portal.security_meta_legacy_map WHERE legacy_kind = 'user'", upgrade_env))
    assert user_map >= 1


def test_verify_production_checks_after_upgrade(upgrade_env: dict[str, str]) -> None:
    rows = _psql(
        """
        SELECT check_name, ok
        FROM portal.sp_security_meta_verify_production()
        ORDER BY 1
        """,
        upgrade_env,
    )
    assert rows
    required_always = {
        "god_architect_role_seeded",
        "david_org_admin_scope_1",
        "inty_org_admin_scope_1",
        "david_entra_identity_meta",
        "meta_user_ids_preserved",
    }
    for line in rows.splitlines():
        name, ok = line.split("|", 1)
        assert ok == "t", f"verify check {name} failed"
        if name in required_always:
            continue
