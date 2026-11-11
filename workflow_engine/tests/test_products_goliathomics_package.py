"""GoliathOmics product package: inheritance + NavTree on fresh Postgres."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SQL_PG = REPO / "workflow_engine" / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"
OMICS_APPLY = REPO / "products" / "goliathomics" / "sql" / "apply_package.sh"
TEST_DB = "goliathomics_package_test"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
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
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(path)], env=env, check=True)


@pytest.fixture(scope="module")
def omics_package_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    admin = _pg_env()
    admin["PGDATABASE"] = "postgres"
    try:
        _psql("SELECT 1", admin)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    _psql(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)', admin)
    _psql(f'CREATE DATABASE "{TEST_DB}"', admin)
    env = _pg_env()
    env["PGDATABASE"] = TEST_DB
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    email = f"omics-pkg-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Omics Pkg', '{email}', 1) RETURNING "ID"
            """,
            env,
        )
    )
    org_row = _psql(f"SELECT * FROM portal.sp_organization_create('OmicsPkg-{user_id}')", env)
    org_id = int(org_row.split("|")[0])
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {user_id})", env)
    _psql_file(NAV_SEED, env)
    subprocess.run(["bash", str(OMICS_APPLY)], env=env, check=True)
    return env


def test_omics_sample_subclasses_platform_material(omics_package_env: dict[str, str]) -> None:
    parent = _psql(
        """
        SELECT parent."Name"
        FROM "Meta"."Classes" child
        INNER JOIN "Meta"."Classes" parent ON parent."ID" = child."ParentID"
        WHERE child."Name" = 'omics/Sample'
        """,
        omics_package_env,
    )
    assert parent == "platform/Material"


def test_omics_nav_registered(omics_package_env: dict[str, str]) -> None:
    count = int(
        _psql(
            """SELECT COUNT(*) FROM portal."NavTree" WHERE "NodePath" LIKE '/app/omics%'""",
            omics_package_env,
        )
    )
    assert count >= 5


def test_god_architect_nav_and_permissions_superset(omics_package_env: dict[str, str]) -> None:
    god_id = int(_psql("SELECT portal.fn_god_architect_role_id()", omics_package_env))
    admin_id = int(
        _psql(
            """SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin' LIMIT 1""",
            omics_package_env,
        )
    )
    admin_perms = _psql(
        f"""
        SELECT string_agg(p."Name", ',' ORDER BY p."Name")
        FROM "RBAC"."Role_Permissions" rp
        INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
        WHERE rp."RoleID" = {admin_id}
        """,
        omics_package_env,
    )
    god_perms = _psql(
        f"""
        SELECT string_agg(p."Name", ',' ORDER BY p."Name")
        FROM "RBAC"."Role_Permissions" rp
        INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
        WHERE rp."RoleID" = {god_id}
        """,
        omics_package_env,
    )
    assert admin_perms
    assert god_perms
    admin_set = set(admin_perms.split(","))
    god_set = set(god_perms.split(","))
    assert admin_set <= god_set
    assert "platform.model.architect" in god_set

    admin_nav = int(
        _psql(f'SELECT COUNT(*) FROM portal."Role2Node" WHERE "RoleId" = {admin_id}', omics_package_env)
    )
    god_nav = int(
        _psql(f'SELECT COUNT(*) FROM portal."Role2Node" WHERE "RoleId" = {god_id}', omics_package_env)
    )
    assert god_nav >= admin_nav > 0
