"""Layered security: class ACL inheritance, object deny, session enforcement."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest

from goliath_app.portal.connection import build_portal_conninfo
from workflow_engine.tests.helpers.portal_session_test_helpers import (
    grant_organization_admin,
    grant_role_nav_tree,
    open_session_token,
)

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"
PORTAL_TEST_PASSWORD = "portal_layered_security_test_pw"


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


def _scoped_role(env: dict[str, str], user_id: int, scope_id: int, perms: list[str]) -> int:
    role_name = f"layered_{uuid.uuid4().hex[:8]}"
    role_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope") VALUES ('{role_name}', false) RETURNING "ID" """,
            env,
        )
    )
    for perm in perms:
        pid = _psql(f"""SELECT "ID" FROM "RBAC"."Permissions" WHERE "Name" = '{perm}' LIMIT 1""", env)
        _psql(
            f"""INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
                SELECT {role_id}, {pid} WHERE NOT EXISTS (
                  SELECT 1 FROM "RBAC"."Role_Permissions" WHERE "RoleID" = {role_id} AND "PermissionID" = {pid}
                )""",
            env,
        )
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'SCOPED', {scope_id}, true, now() AT TIME ZONE 'utc')""",
        env,
    )
    return role_id


@pytest.fixture(scope="module")
def layered_env() -> dict[str, str]:
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


def test_class_inheritance_and_session_get(layered_env: dict[str, str]) -> None:
    env = layered_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    person_id = int(
        _psql("""SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'platform/Person' LIMIT 1""", env)
    )

    admin_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Admin', 'admin-{uuid.uuid4().hex[:8]}@test', 1) RETURNING "ID" """,
            env,
        )
    )
    org = _psql(f"SELECT * FROM portal.sp_organization_create('LayerOrg-{admin_id}')", env)
    org_id = int(org.split("|")[0])
    scope_id = int(org.split("|")[1])
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)], env=env, check=True)
    psql = lambda sql: _psql(sql, env)
    grant_organization_admin(psql, org_id, admin_id)
    admin_role_id = _scoped_role(
        env,
        admin_id,
        scope_id,
        ["platform.security.admin", "meta.schema.read", "meta.object.read", "meta.object.write"],
    )
    grant_role_nav_tree(psql, admin_role_id, scope_id)

    reader_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Reader', 'reader-{uuid.uuid4().hex[:8]}@test', 1) RETURNING "ID" """,
            env,
        )
    )
    restricted_role = int(
        _psql(
            f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
                VALUES ('restricted_{uuid.uuid4().hex[:6]}', false) RETURNING "ID" """,
            env,
        )
    )
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({reader_id}, {restricted_role}, 'SCOPED', {scope_id}, true, now() AT TIME ZONE 'utc')""",
        env,
    )
    _psql(
        f"""SELECT portal.sp_upsert_class_role_access({scope_id}, {restricted_role}, {person_id}, 'read', 'allow')""",
        env,
    )

    admin_token = open_session_token(psql, admin_id, scope_id=scope_id, role_id=admin_role_id)
    with psycopg.connect(build_portal_conninfo()) as conn:
        insert_row = conn.execute(
            "SELECT portal.sp_session_meta_obj_insert(%s, %s, %s::jsonb)",
            (admin_token, "platform/Person", '{"Label": "LayeredTest"}'),
        ).fetchone()
        assert insert_row is not None
        obj_id = insert_row[0]

        child_name = f"e2e/LayerChild_{uuid.uuid4().hex[:4]}"
        child_id = int(
            _psql(
                f"""INSERT INTO "Meta"."Classes" ("Name", "ParentID") VALUES ('{child_name}', {person_id}) RETURNING "ID" """,
                env,
            )
        )
        inherit_row = conn.execute(
            "SELECT portal.fn_meta_effective_class_action(%s, %s, %s, %s)",
            (reader_id, scope_id, child_id, "read"),
        ).fetchone()
        assert inherit_row is not None
        assert inherit_row[0]

    grant_role_nav_tree(psql, restricted_role, scope_id)
    reader_token = open_session_token(psql, reader_id, scope_id=scope_id, role_id=restricted_role)
    with psycopg.connect(build_portal_conninfo()) as conn:
        assert conn.execute(
            "SELECT obj_id FROM portal.sp_session_meta_obj_get(%s, %s)",
            (reader_token, obj_id),
        ).fetchone() is not None

        _psql(
            f"""SELECT portal.sp_upsert_class_role_access({scope_id}, {restricted_role}, {child_id}, 'read', 'deny')""",
            env,
        )
        deny_row = conn.execute(
            "SELECT portal.fn_meta_effective_class_action(%s, %s, %s, %s)",
            (reader_id, scope_id, child_id, "read"),
        ).fetchone()
        assert deny_row is not None
        assert not deny_row[0]


def test_object_deny_gs403(layered_env: dict[str, str]) -> None:
    env = layered_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    user_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('ObjUser', 'obj-{uuid.uuid4().hex[:8]}@test', 1) RETURNING "ID" """,
            env,
        )
    )
    org = _psql(f"SELECT * FROM portal.sp_organization_create('ObjOrg-{user_id}')", env)
    scope_id = int(org.split("|")[1])
    role_id = _scoped_role(
        env, user_id, scope_id, ["meta.schema.read", "meta.object.read", "meta.object.write"]
    )
    person_id = int(
        _psql("""SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'platform/Person' LIMIT 1""", env)
    )
    _psql(
        f"""SELECT portal.sp_upsert_class_role_access({scope_id}, {role_id}, {person_id}, 'read', 'allow')""",
        env,
    )
    psql = lambda sql: _psql(sql, env)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)], env=env, check=True)
    grant_role_nav_tree(psql, role_id, scope_id)
    token = open_session_token(psql, user_id, scope_id=scope_id, role_id=role_id)
    with psycopg.connect(build_portal_conninfo()) as conn:
        obj_row = conn.execute(
            "SELECT portal.sp_session_meta_obj_insert(%s, %s, %s::jsonb)",
            (token, "platform/Person", '{"Label": "DenyMe"}'),
        ).fetchone()
        assert obj_row is not None
        obj_id = obj_row[0]
        _psql(
            f"""SELECT portal.sp_upsert_object_access({scope_id}, {obj_id}, NULL, {user_id}, 'read', 'deny')""",
            env,
        )
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(
                "SELECT obj_id FROM portal.sp_session_meta_obj_get(%s, %s)",
                (token, obj_id),
            )
        assert "GS403" in str(exc.value)
