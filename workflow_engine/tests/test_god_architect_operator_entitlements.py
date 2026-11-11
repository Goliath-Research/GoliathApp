"""God Architect inherits organization_admin operator permissions and nav grants."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"
PRODUCTION_FIXTURE = SQL_PG / "test_fixtures" / "security_meta_production_shape.sql"
UPGRADE_TEST_DB = "goliathapp_god_entitlements_test"


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


def _psql_file(path: Path, env: dict[str, str]) -> None:
    proc = subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)


def _role_ids(env: dict[str, str]) -> tuple[int, int]:
    god = int(_psql("SELECT portal.fn_god_architect_role_id()", env))
    admin = int(
        _psql("""SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin' LIMIT 1""", env)
    )
    return god, admin


def _permission_names(env: dict[str, str], role_id: int) -> set[str]:
    rows = _psql(
        f"""
        SELECT p."Name"
        FROM "RBAC"."Role_Permissions" rp
        INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
        WHERE rp."RoleID" = {role_id}
        ORDER BY 1
        """,
        env,
    )
    if not rows.strip():
        return set()
    return {ln for ln in rows.splitlines() if ln}


def _nav_grant_count(env: dict[str, str], role_id: int, scope_id: int | None = None) -> int:
    scope_filter = "" if scope_id is None else f'AND rn."ScopeId" = {scope_id}'
    return int(
        _psql(
            f"""
            SELECT COUNT(*)::int FROM portal."Role2Node" rn
            WHERE rn."RoleId" = {role_id} {scope_filter}
            """,
            env,
        )
    )


def _assert_god_superset(env: dict[str, str]) -> None:
    god_id, admin_id = _role_ids(env)
    admin_perms = _permission_names(env, admin_id)
    god_perms = _permission_names(env, god_id)
    assert admin_perms <= god_perms
    assert "platform.model.architect" in god_perms
    assert "semantic.restricted.probe" not in god_perms

    god_nav = _nav_grant_count(env, god_id)
    admin_nav = _nav_grant_count(env, admin_id)
    assert god_nav > 0
    assert god_nav >= admin_nav

    scope_line = _psql(
        """
        SELECT MIN(s."ScopeID")::text
        FROM "RBAC"."Scopes" s
        WHERE s."ScopeType" = 'organization' AND COALESCE(s."Active", true)
        """,
        env,
    )
    if scope_line:
        scope_id = int(scope_line)
        assert _nav_grant_count(env, god_id, scope_id) >= _nav_grant_count(env, admin_id, scope_id)


@pytest.fixture(scope="module")
def fresh_apply_nav_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    email = f"god-ent-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('God Entitlements', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )
    org_row = _psql(
        f"SELECT * FROM portal.sp_organization_create('GodEntOrg-{user_id}')",
        env,
    )
    org_id = int(org_row.split("|")[0])
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {user_id})", env)
    _psql_file(NAV_SEED, env)
    return env


@pytest.fixture(scope="module")
def upgrade_nav_env() -> dict[str, str]:
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
    _psql_file(PRODUCTION_FIXTURE, env)
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    _psql_file(NAV_SEED, env)
    return env


def test_god_architect_superset_after_apply_and_nav_seed(fresh_apply_nav_env: dict[str, str]) -> None:
    _assert_god_superset(fresh_apply_nav_env)
    _psql("SELECT portal.sp_sync_god_architect_operator_entitlements()", fresh_apply_nav_env)
    _assert_god_superset(fresh_apply_nav_env)


def test_god_architect_superset_idempotent_sync(fresh_apply_nav_env: dict[str, str]) -> None:
    god_id, _ = _role_ids(fresh_apply_nav_env)
    before = _permission_names(fresh_apply_nav_env, god_id)
    _psql("SELECT portal.sp_sync_god_architect_operator_entitlements()", fresh_apply_nav_env)
    _psql("SELECT portal.sp_sync_god_architect_operator_entitlements()", fresh_apply_nav_env)
    after = _permission_names(fresh_apply_nav_env, god_id)
    assert before == after


def test_god_architect_superset_after_upgrade_path(upgrade_nav_env: dict[str, str]) -> None:
    _assert_god_superset(upgrade_nav_env)
