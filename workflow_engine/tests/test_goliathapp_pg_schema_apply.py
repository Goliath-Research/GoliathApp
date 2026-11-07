"""Apply GoliathApp PostgreSQL schema twice (idempotent) and smoke-test organization APIs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from workflow_engine.tests.pg_require_ci import require_postgres_reachable, require_psql

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
MIGRATIONS = SQL_PG / "migrations"
APPLY_SH = SQL_PG / "apply_schema.sh"
PORTAL_RBAC_SQL = SQL_PG / "portal_rbac_api.sql"


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


def _pg_test_env() -> dict[str, str]:
    """Libpq env with localhost default password; fails in CI when psql or DB is unavailable."""
    require_psql()
    env = _pg_env()
    if not env.get("PGPASSWORD") and env.get("PGHOST", "localhost") in ("localhost", "127.0.0.1"):
        env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath"))
    def _probe() -> None:
        _psql("SELECT 1", env)

    require_postgres_reachable(_probe)
    return env


@pytest.fixture(scope="module")
def pg_schema_applied() -> dict[str, str]:
    env = _pg_test_env()
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
    meta_obj_id = _psql(
        f'SELECT "MetaObjID" FROM portal."NavTree" WHERE "ID" = {node_id}',
        env,
    )
    assert int(meta_obj_id) > 0


def test_portal_nav_meta_catalog_installed(pg_schema_applied: dict[str, str]) -> None:
    env = pg_schema_applied
    class_id = _psql("SELECT portal.fn_nav_node_class_id()", env)
    link_id = _psql("SELECT portal.fn_nav_parent_metalink_id()", env)
    assert int(class_id) > 0
    assert int(link_id) > 0


def test_nav_tree_migration_readonly_scripts_execute(pg_schema_applied: dict[str, str]) -> None:
    env = pg_schema_applied
    preflight = MIGRATIONS / "20261107_nav_tree_meta__00_preflight_readonly.sql"
    verify = MIGRATIONS / "20261107_nav_tree_meta__99_verify_readonly.sql"
    for path in (preflight, verify):
        subprocess.run(
            ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(path)],
            env=env,
            check=True,
        )


def test_portal_rbac_api_survives_return_type_change() -> None:
    """Re-applying portal_rbac_api.sql must replace an older row shape (CREATE OR REPLACE is not enough)."""
    env = _pg_test_env()
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    # PostgreSQL rejects CREATE OR REPLACE when the row type changes; drop first like an older DB would after upgrade mismatch.
    subprocess.run(
        [
            "psql",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "DROP FUNCTION IF EXISTS portal.sp_list_scopes(boolean);",
        ],
        env=env,
        check=True,
    )
    # Simulate a prior release with a narrower RETURNS TABLE (repro Neon row-type error).
    _psql("DROP FUNCTION IF EXISTS portal.sp_list_scopes(boolean)", env)
    stub = r"""
    CREATE FUNCTION portal.sp_list_scopes(p_include_inactive boolean DEFAULT false)
    RETURNS TABLE (scope_id int)
    LANGUAGE sql
    STABLE
    AS $$
      SELECT 1::int AS scope_id WHERE false;
    $$;
    """
    subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-c", stub],
        env=env,
        check=True,
    )
    subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(PORTAL_RBAC_SQL)],
        env=env,
        check=True,
    )
    _psql(
        "SELECT organization_id FROM portal.sp_list_scopes(false) LIMIT 0",
        env,
    )
