"""Official platform baseline NavTree seed (seed_platform_nav_tree.sql)."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest

from goliath_app.portal import PortalClient
from goliath_app.portal.connection import build_portal_conninfo

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"
PORTAL_TEST_PASSWORD = "platform_nav_seed_test_pw"

BASELINE_PATHS: tuple[str, ...] = (
    "/app",
    "/app/admin/users",
    "/app/meta/classes",
    "/app/meta/methods",
    "/app/meta/relations",
    "/app/workflows/definitions",
    "/app/semantic/entities",
    "/app/config/site",
    "/app/operations/events",
    "/app/views/dashboards",
    "/app/inv/items",
)

EXPECTED_BASELINE_NODE_COUNT = 45


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


@pytest.fixture(scope="module")
def platform_nav_seed_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    escaped = PORTAL_TEST_PASSWORD.replace("'", "''")
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'", env)
    return env


def test_platform_nav_seed_idempotent_and_grants(platform_nav_seed_env: dict[str, str]) -> None:
    env = platform_nav_seed_env
    for _ in range(2):
        _psql_file(NAV_SEED, env)

    baseline_count = int(
        _psql(
            """SELECT count(*) FROM portal."NavTree" WHERE "NodePath" LIKE '/app%'""",
            env,
        )
    )
    assert baseline_count == EXPECTED_BASELINE_NODE_COUNT

    for path in BASELINE_PATHS:
        found = _psql(
            f"""SELECT count(*) FROM portal."NavTree" WHERE "NodePath" = '{path.replace("'", "''")}'""",
            env,
        )
        assert int(found) == 1, path

    role_id = int(
        _psql(
            """SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin' LIMIT 1""",
            env,
        )
    )
    meta_perm_count = int(
        _psql(
            f"""
            SELECT count(*)
            FROM "RBAC"."Role_Permissions" rp
            INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
            WHERE rp."RoleID" = {role_id}
              AND p."Name" IN (
                'meta.schema.read', 'meta.object.read', 'meta.object.write'
              )
            """,
            env,
        )
    )
    assert meta_perm_count == 3

    email = f"nav-seed-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Nav Seed', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )
    org_row = _psql(
        f"SELECT * FROM portal.sp_organization_create('NavSeedOrg-{user_id}')",
        env,
    )
    scope_id = int(org_row.split("|")[1])
    _psql(
        f"SELECT grant_id FROM portal.sp_organization_set_admin({int(org_row.split('|')[0])}, {user_id})",
        env,
    )

    _psql_file(NAV_SEED, env)

    grant_count = int(
        _psql(
            f"""
            SELECT count(*)
            FROM portal."Role2Node" rn
            WHERE rn."RoleId" = {role_id}
              AND rn."ScopeId" = {scope_id}
            """,
            env,
        )
    )
    assert grant_count == EXPECTED_BASELINE_NODE_COUNT

    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    os.environ.setdefault("PGHOST", env["PGHOST"])
    os.environ.setdefault("PGPORT", env["PGPORT"])
    os.environ.setdefault("PGDATABASE", env["PGDATABASE"])
    client = PortalClient(build_portal_conninfo())
    opened = client.session_open(user_id, active_scope_id=scope_id)
    with psycopg.connect(build_portal_conninfo()) as conn:
        cur = conn.execute(
            "SELECT caption FROM portal.sp_session_operator_nav_tree(%s) ORDER BY caption",
            (opened.session_token,),
        )
        captions = {str(r[0]) for r in cur.fetchall()}
    assert "Platform" in captions
    assert "Meta model" in captions
    assert "Workflows" in captions


def test_platform_nav_seed_twice_without_duplicate_nodes(platform_nav_seed_env: dict[str, str]) -> None:
    env = platform_nav_seed_env
    _psql_file(NAV_SEED, env)
    first = int(_psql("""SELECT count(*) FROM portal."NavTree" WHERE "NodePath" LIKE '/app%'""", env))
    _psql_file(NAV_SEED, env)
    second = int(_psql("""SELECT count(*) FROM portal."NavTree" WHERE "NodePath" LIKE '/app%'""", env))
    assert first == second == EXPECTED_BASELINE_NODE_COUNT
