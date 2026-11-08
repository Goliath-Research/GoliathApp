"""Session-bound operator navigation (portal.sp_session_operator_nav_tree)."""

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
PORTAL_TEST_PASSWORD = "portal_session_nav_test_pw"


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
def portal_nav_env() -> dict[str, str]:
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
    _psql(
        f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'",
        env,
    )
    return env


@pytest.fixture(scope="module")
def portal_client(portal_nav_env: dict[str, str]) -> PortalClient:
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    os.environ.setdefault("PGHOST", portal_nav_env["PGHOST"])
    os.environ.setdefault("PGPORT", portal_nav_env["PGPORT"])
    os.environ.setdefault("PGDATABASE", portal_nav_env["PGDATABASE"])
    return PortalClient(build_portal_conninfo())


def test_session_nav_denied_without_token(portal_nav_env: dict[str, str]) -> None:
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    os.environ.setdefault("PGHOST", portal_nav_env["PGHOST"])
    os.environ.setdefault("PGPORT", portal_nav_env["PGPORT"])
    os.environ.setdefault("PGDATABASE", portal_nav_env["PGDATABASE"])
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT node_id FROM portal.sp_session_operator_nav_tree('')",
            )
        assert "GS401" in str(excinfo.value)


def _nav_captions(conninfo: str, token: str) -> set[str]:
    with psycopg.connect(conninfo) as conn:
        cur = conn.execute(
            "SELECT caption FROM portal.sp_session_operator_nav_tree(%s)",
            (token,),
        )
        return {str(r[0]) for r in cur.fetchall()}


def test_session_nav_empty_without_active_scope(
    portal_client: PortalClient,
    portal_nav_env: dict[str, str],
) -> None:
    email = f"nav-noscope-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('No Scope', '{email}', 1)
            RETURNING "ID"
            """,
            portal_nav_env,
        )
    )
    opened = portal_client.session_open(user_id, active_scope_id=None)
    conninfo = build_portal_conninfo()
    assert _nav_captions(conninfo, opened.session_token) == set()


def test_session_nav_denies_other_org_scope(
    portal_client: PortalClient,
    portal_nav_env: dict[str, str],
) -> None:
    email = f"nav-tenant-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Tenant Nav', '{email}', 1)
            RETURNING "ID"
            """,
            portal_nav_env,
        )
    )
    org_a = _psql(f"SELECT * FROM portal.sp_organization_create('NavOrgA-{user_id}')", portal_nav_env)
    scope_a = int(org_a.split("|")[1])
    org_b = _psql(f"SELECT * FROM portal.sp_organization_create('NavOrgB-{user_id}')", portal_nav_env)
    scope_b = int(org_b.split("|")[1])
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({int(org_a.split('|')[0])}, {user_id})", portal_nav_env)
    node_id = int(
        _psql(
            "SELECT node_id FROM portal.sp_nav_register_node(NULL, 'ScopeAOnly', 11::smallint)",
            portal_nav_env,
        )
    )
    role_id = int(
        _psql(
            """SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin' LIMIT 1""",
            portal_nav_env,
        )
    )
    _psql(
        f"SELECT ok FROM portal.sp_grant_role_nav_node({role_id}, {node_id}, {scope_a})",
        portal_nav_env,
    )
    conninfo = build_portal_conninfo()
    opened_wrong_scope = portal_client.session_open(user_id, active_scope_id=scope_b)
    assert "ScopeAOnly" not in _nav_captions(conninfo, opened_wrong_scope.session_token)

    opened_right_scope = portal_client.session_open(user_id, active_scope_id=scope_a)
    assert "ScopeAOnly" in _nav_captions(conninfo, opened_right_scope.session_token)


def test_session_nav_rejects_inactive_user(
    portal_client: PortalClient,
    portal_nav_env: dict[str, str],
) -> None:
    email = f"nav-inactive-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Inactive', '{email}', 1)
            RETURNING "ID"
            """,
            portal_nav_env,
        )
    )
    opened = portal_client.session_open(user_id)
    _psql(f'UPDATE "RBAC"."Users" SET "Active" = 0 WHERE "ID" = {user_id}', portal_nav_env)
    conninfo = build_portal_conninfo()
    with pytest.raises(psycopg.Error) as excinfo:
        _nav_captions(conninfo, opened.session_token)
    assert "GS401" in str(excinfo.value)


def test_session_nav_rejects_expired_token(
    portal_client: PortalClient,
    portal_nav_env: dict[str, str],
) -> None:
    email = f"nav-expired-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Expired', '{email}', 1)
            RETURNING "ID"
            """,
            portal_nav_env,
        )
    )
    opened = portal_client.session_open(user_id)
    _psql(
        f"""
        UPDATE "RBAC"."SessionTokens" st
        SET "ExpiresAtUtc" = (now() AT TIME ZONE 'utc') - interval '1 minute'
        FROM "RBAC"."Sessions" s
        WHERE st."SessionID" = s."ID" AND s."UserID" = {user_id}
        """,
        portal_nav_env,
    )
    conninfo = build_portal_conninfo()
    with pytest.raises(psycopg.Error) as excinfo:
        _nav_captions(conninfo, opened.session_token)
    assert "GS401" in str(excinfo.value)


def test_session_nav_respects_role2node(
    portal_client: PortalClient,
    portal_nav_env: dict[str, str],
) -> None:
    email = f"nav-user-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Nav Tester', '{email}', 1)
            RETURNING "ID"
            """,
            portal_nav_env,
        )
    )
    org_row = _psql(
        f"SELECT * FROM portal.sp_organization_create('NavOrg-{user_id}')",
        portal_nav_env,
    )
    org_id, scope_id = (int(x) for x in org_row.split("|"))
    _psql(
        f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {user_id})",
        portal_nav_env,
    )
    node_id = int(
        _psql(
            "SELECT node_id FROM portal.sp_nav_register_node(NULL, 'P1Nav', 10::smallint)",
            portal_nav_env,
        )
    )
    role_id = int(
        _psql(
            """SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin' LIMIT 1""",
            portal_nav_env,
        )
    )
    _psql(
        f"SELECT ok FROM portal.sp_grant_role_nav_node({role_id}, {node_id}, {scope_id})",
        portal_nav_env,
    )

    opened = portal_client.session_open(user_id, active_scope_id=scope_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        cur = conn.execute(
            """
            SELECT node_id, caption
            FROM portal.sp_session_operator_nav_tree(%s)
            """,
            (opened.session_token,),
        )
        rows = {int(r[0]): str(r[1]) for r in cur.fetchall()}
    assert node_id in rows
    assert rows[node_id] == "P1Nav"

    portal_client.session_revoke(opened.session_token)
    with pytest.raises(psycopg.Error) as excinfo:
        with psycopg.connect(conninfo) as conn:
            conn.execute(
                "SELECT node_id FROM portal.sp_session_operator_nav_tree(%s)",
                (opened.session_token,),
            )
    assert "GS401" in str(excinfo.value)
