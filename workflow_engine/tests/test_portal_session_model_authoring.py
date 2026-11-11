"""Session-bound platform model authoring APIs."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"
PORTAL_TEST_PASSWORD = "portal_model_author_test_pw"


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


def _grant_platform_author(env: dict[str, str], user_id: int, scope_id: int) -> int:
    perm_id = _psql(
        """SELECT "ID" FROM "RBAC"."Permissions" WHERE "Name" = 'platform.model.author' LIMIT 1""",
        env,
    )
    role_name = f"model_author_{uuid.uuid4().hex[:8]}"
    role_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope") VALUES ('{role_name}', false) RETURNING "ID" """,
            env,
        )
    )
    _psql(
        f"""INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
            SELECT {role_id}, {perm_id}
            WHERE NOT EXISTS (
              SELECT 1 FROM "RBAC"."Role_Permissions" WHERE "RoleID" = {role_id} AND "PermissionID" = {perm_id}
            )""",
        env,
    )
    for perm in ("meta.schema.read", "meta.object.read", "meta.object.write"):
        pid = _psql(f"""SELECT "ID" FROM "RBAC"."Permissions" WHERE "Name" = '{perm}' LIMIT 1""", env)
        _psql(
            f"""INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
                SELECT {role_id}, {pid}
                WHERE NOT EXISTS (
                  SELECT 1 FROM "RBAC"."Role_Permissions" WHERE "RoleID" = {role_id} AND "PermissionID" = {pid}
                )""",
            env,
        )
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'DIRECT', {scope_id}, true, now() AT TIME ZONE 'utc')""",
        env,
    )
    return role_id


@pytest.fixture(scope="module")
def model_author_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    for _ in range(2):
        subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    escaped = PORTAL_TEST_PASSWORD.replace("'", "''")
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'", env)
    return env


def test_platform_generic_classes_installed(model_author_env: dict[str, str]) -> None:
    env = model_author_env
    count = int(
        _psql("""SELECT count(*) FROM "Meta"."Classes" WHERE "Name" LIKE 'platform/%'""", env)
    )
    assert count >= 14


def test_session_model_author_denied_without_permission(model_author_env: dict[str, str]) -> None:
    from goliath_app.portal import PortalClient
    from goliath_app.portal.connection import build_portal_conninfo

    env = model_author_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    email = f"denied-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active") VALUES ('Denied', '{email}', 1) RETURNING "ID" """,
            env,
        )
    )
    org = _psql(f"SELECT * FROM portal.sp_organization_create('DenyOrg-{user_id}')", env)
    scope_id = int(org.split("|")[1])
    client = PortalClient(build_portal_conninfo())
    opened = client.session_open(user_id, active_scope_id=scope_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(
                "SELECT class_id FROM portal.sp_session_meta_class_create(%s, %s, %s)",
                (opened.session_token, "your_app/NoPerm", "platform/Entity"),
            )
        assert "GS403" in str(exc.value)


def test_session_model_author_create_subclass_and_export(model_author_env: dict[str, str]) -> None:
    from goliath_app.portal import PortalClient
    from goliath_app.portal.connection import build_portal_conninfo

    env = model_author_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    email = f"author-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active") VALUES ('Author', '{email}', 1) RETURNING "ID" """,
            env,
        )
    )
    org = _psql(f"SELECT * FROM portal.sp_organization_create('AuthOrg-{user_id}')", env)
    org_id = int(org.split("|")[0])
    scope_id = int(org.split("|")[1])
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)], env=env, check=True)
    from workflow_engine.tests.helpers.portal_session_test_helpers import (
        grant_organization_admin,
        grant_role_nav_tree,
        open_session_token,
    )

    psql = lambda sql: _psql(sql, env)
    grant_organization_admin(psql, org_id, user_id)
    author_role_id = _grant_platform_author(env, user_id, scope_id)
    grant_role_nav_tree(psql, author_role_id, scope_id)
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    session_token = open_session_token(psql, user_id, scope_id=scope_id, role_id=author_role_id)
    class_name = f"your_app/TestParty_{uuid.uuid4().hex[:6]}"
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        cur = conn.execute(
            "SELECT class_id, class_name FROM portal.sp_session_meta_class_create(%s, %s, %s)",
            (session_token, class_name, "platform/Person"),
        )
        row = cur.fetchone()
        assert row is not None
        conn.execute(
            "SELECT field_id FROM portal.sp_session_meta_field_upsert(%s, %s, %s, %s, %s, %s)",
            (session_token, class_name, "Nickname", "portal/nav/Caption", "1.0", True),
        )
        pkg = conn.execute(
            "SELECT package_sql FROM portal.sp_session_export_model_package(%s, %s)",
            (session_token, "your_app/"),
        ).fetchone()
        assert pkg is not None
        assert class_name in str(pkg[0])
