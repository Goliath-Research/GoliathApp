"""God Architect platform model authority."""

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
PORTAL_TEST_PASSWORD = "platform_god_architect_test_pw"


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
def god_env() -> dict[str, str]:
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


def test_god_architect_seeded_and_david_global_grant(god_env: dict[str, str]) -> None:
    role_id = int(_psql("SELECT portal.fn_god_architect_role_id()", god_env))
    assert role_id > 0
    perm = _psql(
        """SELECT COUNT(*) FROM "RBAC"."Permissions" p WHERE p."Name" = 'platform.model.architect'""",
        god_env,
    )
    assert int(perm) == 1

    rows = _psql(
        """
        SELECT check_name, ok FROM portal.sp_security_meta_verify_production()
        WHERE check_name IN ('god_architect_role_seeded', 'david_god_architect_global')
        ORDER BY 1
        """,
        god_env,
    )
    for line in rows.splitlines():
        name, ok = line.split("|")
        assert ok == "t", f"verify check {name} failed"


def test_organization_admin_cannot_author_platform_class(god_env: dict[str, str]) -> None:
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    email = f"org-admin-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Org Admin', '{email}', 1) RETURNING "ID"
            """,
            god_env,
        )
    )
    org = _psql(f"SELECT * FROM portal.sp_organization_create('GodArchGate-{user_id}')", god_env)
    org_id, scope_id = (int(x) for x in org.split("|"))
    grant = _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {user_id})", god_env)
    try:
        _psql(f"SELECT portal.sp_security_meta_upsert_role_grant_from_rbac({grant})", god_env)
    except RuntimeError:
        pass

    client = PortalClient(build_portal_conninfo())
    token = client.session_open(user_id, active_scope_id=scope_id).session_token
    conninfo = build_portal_conninfo()
    class_name = f"platform/GateTest{uuid.uuid4().hex[:6]}"
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(
                "SELECT class_id FROM portal.sp_session_meta_class_create(%s, %s, NULL)",
                (token, class_name),
            )
        assert "GS403" in str(exc.value)


def test_god_architect_selectable_for_user_with_global_grant(god_env: dict[str, str]) -> None:
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    god_role = int(_psql("SELECT portal.fn_god_architect_role_id()", god_env))
    _psql("SELECT portal.sp_security_meta_grant_god_architect_to_user(1)", god_env)

    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        roles = conn.execute(
            "SELECT role_id FROM portal.fn_session_user_selectable_role_ids(1, 1)"
        ).fetchall()
        role_ids = {int(r[0]) for r in roles}
        assert god_role in role_ids
