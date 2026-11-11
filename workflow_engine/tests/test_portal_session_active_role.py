"""Session active role selection (portal.sp_session_set_active_role)."""

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
PORTAL_TEST_PASSWORD = "portal_active_role_test_pw"


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
def portal_role_env() -> dict[str, str]:
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


@pytest.fixture(scope="module")
def portal_client(portal_role_env: dict[str, str]) -> PortalClient:
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    os.environ.setdefault("PGHOST", portal_role_env["PGHOST"])
    os.environ.setdefault("PGPORT", portal_role_env["PGPORT"])
    os.environ.setdefault("PGDATABASE", portal_role_env["PGDATABASE"])
    return PortalClient(build_portal_conninfo())


def test_rejects_ungranted_active_role(portal_client: PortalClient, portal_role_env: dict[str, str]) -> None:
    email = f"role-guard-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Role Guard', '{email}', 1)
            RETURNING "ID"
            """,
            portal_role_env,
        )
    )
    org_row = _psql(f"SELECT * FROM portal.sp_organization_create('RoleOrg-{user_id}')", portal_role_env)
    scope_id = int(org_row.split("|")[1])
    bogus_role = int(_psql('SELECT "ID" FROM "RBAC"."Roles" ORDER BY "ID" DESC LIMIT 1', portal_role_env))
    opened = portal_client.session_open(user_id, active_scope_id=scope_id)
    conninfo = build_portal_conninfo()
    with pytest.raises(psycopg.Error) as excinfo:
        with psycopg.connect(conninfo) as conn:
            conn.execute(
                "SELECT role_id FROM portal.sp_session_set_active_role(%s, %s)",
                (opened.session_token, bogus_role),
            )
    assert "GS403" in str(excinfo.value)


def test_single_role_auto_selected_and_nav_isolated(
    portal_client: PortalClient,
    portal_role_env: dict[str, str],
) -> None:
    email = f"role-dual-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Dual Role', '{email}', 1)
            RETURNING "ID"
            """,
            portal_role_env,
        )
    )
    org_row = _psql(f"SELECT * FROM portal.sp_organization_create('DualOrg-{user_id}')", portal_role_env)
    org_id, scope_id = (int(x) for x in org_row.split("|"))
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {user_id})", portal_role_env)
    role_admin = int(_psql("""SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin' LIMIT 1""", portal_role_env))
    role_other = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
            VALUES ('nav_only_{user_id}', false)
            RETURNING "ID"
            """,
            portal_role_env,
        )
    )
    _psql(
        f"""
        INSERT INTO "RBAC"."UserRoleGrants"
          ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
        VALUES ({user_id}, {role_other}, 'SCOPED', {scope_id}, true, now() AT TIME ZONE 'utc')
        """,
        portal_role_env,
    )
    node_admin = int(
        _psql("SELECT node_id FROM portal.sp_nav_register_node(NULL, 'AdminLeaf', 10::smallint)", portal_role_env)
    )
    node_other = int(
        _psql("SELECT node_id FROM portal.sp_nav_register_node(NULL, 'OtherLeaf', 11::smallint)", portal_role_env)
    )
    _psql(f"SELECT ok FROM portal.sp_grant_role_nav_node({role_admin}, {node_admin}, {scope_id})", portal_role_env)
    _psql(f"SELECT ok FROM portal.sp_grant_role_nav_node({role_other}, {node_other}, {scope_id})", portal_role_env)

    opened = portal_client.session_open(user_id, active_scope_id=scope_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        state = conn.execute(
            "SELECT active_role_id, selectable_count FROM portal.sp_session_get_active_role_state(%s)",
            (opened.session_token,),
        ).fetchone()
    assert state is not None
    assert int(state[1]) == 2
    assert state[0] is None

    with psycopg.connect(conninfo) as conn:
        conn.execute(
            "SELECT role_id FROM portal.sp_session_set_active_role(%s, %s)",
            (opened.session_token, role_other),
        )
        captions = {
            str(r[0])
            for r in conn.execute(
                "SELECT caption FROM portal.sp_session_operator_nav_tree(%s)",
                (opened.session_token,),
            )
        }
    assert captions == {"OtherLeaf"}
