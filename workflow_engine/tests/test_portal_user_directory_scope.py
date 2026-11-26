"""Organization administrators must not read another tenant's user directory.

The session organization (active scope) is the object the admin check authorizes.
``portal.sp_session_list_users_admin`` and ``portal.sp_session_list_users`` are the
two product reads of that directory: the Users page and security API call the
first, and the Navigation page calls the second. Both must return only people
who are members of the session organization or who hold a role grant in the
active scope.

These tests fail while either function still returns the whole catalog.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from shutil import which

import psycopg
import pytest

from goliath_app.portal.connection import build_portal_conninfo
from workflow_engine.tests.helpers.portal_session_test_helpers import (
    grant_organization_admin,
    open_session_token,
    organization_admin_role_id,
)

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"


@dataclass(frozen=True)
class Person:
    user_id: int
    full_name: str
    email: str


@dataclass(frozen=True)
class DirectoryFixture:
    env: dict[str, str]
    scope_a: int
    scope_b: int
    caller: Person
    member_a: Person
    grant_a: Person
    member_b: Person
    grant_b: Person
    stranger: Person
    token_scope_a: str
    token_scope_b: str


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    if not env.get("PGPASSWORD") and os.environ.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = os.environ["POSTGRES_PASSWORD"]
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


def _insert_user(env: dict[str, str], full_name: str, email: str) -> Person:
    user_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('{full_name}', '{email}', 1) RETURNING "ID" """,
            env,
        )
    )
    return Person(user_id=user_id, full_name=full_name, email=email)


def _create_role(env: dict[str, str], name: str) -> int:
    return int(
        _psql(
            f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
                VALUES ('{name}', false) RETURNING "ID" """,
            env,
        )
    )


def _grant_scoped_role(env: dict[str, str], user_id: int, role_id: int, scope_id: int) -> None:
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants"
              ("UserID","RoleID","GrantType","ScopeID","Active","GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'SCOPED', {scope_id}, true, now())""",
        env,
    )


def _visible(scope: str, fx: DirectoryFixture) -> tuple[Person, ...]:
    if scope == "a":
        return (fx.caller, fx.member_a, fx.grant_a)
    return (fx.caller, fx.member_b, fx.grant_b)


def _hidden(scope: str, fx: DirectoryFixture) -> tuple[Person, ...]:
    if scope == "a":
        return (fx.member_b, fx.grant_b, fx.stranger)
    return (fx.member_a, fx.grant_a, fx.stranger)


def _assert_scoped(rows: list[tuple[object, ...]], visible: tuple[Person, ...], hidden: tuple[Person, ...]) -> None:
    emails = {str(row[2]) for row in rows}
    names = {str(row[1]) for row in rows}
    missing = [person.email for person in visible if person.email not in emails or person.full_name not in names]
    leaked = [person.email for person in hidden if person.email in emails or person.full_name in names]
    assert not missing, f"session organization members missing from the directory: {missing}"
    assert not leaked, f"users outside the session organization were returned: {leaked}"


@pytest.fixture(scope="module")
def directory_fx() -> DirectoryFixture:
    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    if not env.get("PGPASSWORD"):
        pytest.skip("PostgreSQL password is not configured")
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)], env=env, check=True)

    portal_password = secrets.token_hex(16)
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{portal_password}'", env)
    os.environ["GOLIATH_PORTAL_PASSWORD"] = portal_password
    env["GOLIATH_PORTAL_PASSWORD"] = portal_password

    token = uuid.uuid4().hex[:8]
    psql = lambda sql: _psql(sql, env)  # noqa: E731

    org_a = _psql("SELECT * FROM portal.sp_organization_create('DirOrgA')", env)
    org_b = _psql("SELECT * FROM portal.sp_organization_create('DirOrgB')", env)
    org_a_id, scope_a = int(org_a.split("|")[0]), int(org_a.split("|")[1])
    org_b_id, scope_b = int(org_b.split("|")[0]), int(org_b.split("|")[1])

    caller = _insert_user(env, f"Caller {token}", f"c{token}@ex.test")
    member_a = _insert_user(env, f"MemberA {token}", f"ma{token}@ex.test")
    grant_a = _insert_user(env, f"GrantA {token}", f"ga{token}@ex.test")
    member_b = _insert_user(env, f"MemberB {token}", f"mb{token}@ex.test")
    grant_b = _insert_user(env, f"GrantB {token}", f"gb{token}@ex.test")
    stranger = _insert_user(env, f"Stranger {token}", f"st{token}@ex.test")

    grant_organization_admin(psql, org_a_id, caller.user_id)
    grant_organization_admin(psql, org_b_id, caller.user_id)
    _psql(f"SELECT inserted FROM portal.sp_organization_add_member({org_a_id}, {member_a.user_id})", env)
    _psql(f"SELECT inserted FROM portal.sp_organization_add_member({org_b_id}, {member_b.user_id})", env)

    role_a = _create_role(env, f"dir_role_a_{token}")
    role_b = _create_role(env, f"dir_role_b_{token}")
    _grant_scoped_role(env, grant_a.user_id, role_a, scope_a)
    _grant_scoped_role(env, grant_b.user_id, role_b, scope_b)

    # The admin list reads platform/User rows. Schema apply copies the catalog
    # once; users created after that are copied by the same product function.
    _psql("SELECT portal.sp_security_meta_migrate_from_legacy()", env)
    _psql("SELECT portal.sp_security_meta_refresh_cache()", env)

    admin_role = organization_admin_role_id(psql)
    token_scope_a = open_session_token(psql, caller.user_id, scope_id=scope_a, role_id=admin_role)
    token_scope_b = open_session_token(psql, caller.user_id, scope_id=scope_b, role_id=admin_role)

    return DirectoryFixture(
        env=env,
        scope_a=scope_a,
        scope_b=scope_b,
        caller=caller,
        member_a=member_a,
        grant_a=grant_a,
        member_b=member_b,
        grant_b=grant_b,
        stranger=stranger,
        token_scope_a=token_scope_a,
        token_scope_b=token_scope_b,
    )


def _portal(env: dict[str, str]):
    os.environ["PGHOST"] = env["PGHOST"]
    os.environ["PGPORT"] = env["PGPORT"]
    os.environ["PGDATABASE"] = env["PGDATABASE"]
    os.environ["GOLIATH_PORTAL_PASSWORD"] = env["GOLIATH_PORTAL_PASSWORD"]
    return psycopg.connect(build_portal_conninfo())


def _assert_active_scope(conn: psycopg.Connection, token: str, scope_id: int) -> None:
    row = conn.execute(
        """SELECT active_scope_id, active_role_name
           FROM portal.fn_session_resolve(%s)""",
        (token,),
    ).fetchone()
    assert row is not None
    assert int(row[0]) == scope_id
    assert row[1] == "organization_admin"


def test_org_admin_user_admin_list_follows_active_scope(directory_fx: DirectoryFixture) -> None:
    fx = directory_fx
    with _portal(fx.env) as conn:
        _assert_active_scope(conn, fx.token_scope_a, fx.scope_a)
        rows_a = conn.execute(
            """SELECT user_id, full_name, email
               FROM portal.sp_session_list_users_admin(%s)""",
            (fx.token_scope_a,),
        ).fetchall()
        _assert_scoped(rows_a, _visible("a", fx), _hidden("a", fx))

        _assert_active_scope(conn, fx.token_scope_b, fx.scope_b)
        rows_b = conn.execute(
            """SELECT user_id, full_name, email
               FROM portal.sp_session_list_users_admin(%s)""",
            (fx.token_scope_b,),
        ).fetchall()
        _assert_scoped(rows_b, _visible("b", fx), _hidden("b", fx))


def test_org_admin_platform_user_list_follows_active_scope(directory_fx: DirectoryFixture) -> None:
    fx = directory_fx
    with _portal(fx.env) as conn:
        _assert_active_scope(conn, fx.token_scope_a, fx.scope_a)
        rows_a = conn.execute(
            """SELECT user_id, full_name, email
               FROM portal.sp_session_list_users(%s, false)""",
            (fx.token_scope_a,),
        ).fetchall()
        _assert_scoped(rows_a, _visible("a", fx), _hidden("a", fx))

        _assert_active_scope(conn, fx.token_scope_b, fx.scope_b)
        rows_b = conn.execute(
            """SELECT user_id, full_name, email
               FROM portal.sp_session_list_users(%s, false)""",
            (fx.token_scope_b,),
        ).fetchall()
        _assert_scoped(rows_b, _visible("b", fx), _hidden("b", fx))


def test_member_without_admin_role_cannot_list_the_directory(directory_fx: DirectoryFixture) -> None:
    fx = directory_fx
    token = open_session_token(lambda sql: _psql(sql, fx.env), fx.member_a.user_id, scope_id=fx.scope_a)
    with _portal(fx.env) as conn:
        with pytest.raises(psycopg.Error) as admin_list:
            conn.execute("SELECT email FROM portal.sp_session_list_users_admin(%s)", (token,))
        assert "GS403" in str(admin_list.value)
        conn.rollback()
        with pytest.raises(psycopg.Error) as platform_list:
            conn.execute("SELECT email FROM portal.sp_session_list_users(%s, false)", (token,))
        assert "GS403" in str(platform_list.value)
