"""Organization-admin user upsert must not mutate accounts outside the caller org.

The portal security action ``upsert_user`` calls ``portal.sp_session_upsert_user``,
which updates ``RBAC.Users`` by email for the whole database and then adds that
person to the caller's organization. These tests are the expected behavior:

- an organization administrator may create a new user for their own organization
- the same call must not rename, deactivate, or adopt a user who is not a member
- the global ``Active`` flag must not be cleared, including for an existing member
- a refused call must leave the target row, memberships, and live session intact

They fail while the global upsert is still in place.

Not covered here: ``portal.sp_upsert_user`` has no separate HTTP action (only this
session wrapper calls it), invitation acceptance sets ``Active`` true for the
person who signs in, and ``sp_session_list_users_admin`` is a read.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest

from workflow_engine.tests.helpers.portal_session_test_helpers import (
    grant_organization_admin,
    open_session_token,
)

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"


def _pg_env() -> dict[str, str]:
    password = os.environ.get("POSTGRES_PASSWORD")
    if not password:
        pytest.skip("POSTGRES_PASSWORD is not set")
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    env["PGPASSWORD"] = password
    env["POSTGRES_PASSWORD"] = password
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


def _connect(env: dict[str, str]) -> psycopg.Connection:
    return psycopg.connect(
        host=env["PGHOST"],
        port=int(env["PGPORT"]),
        user=env["PGUSER"],
        password=env["PGPASSWORD"],
        dbname=env["PGDATABASE"],
    )


@pytest.fixture(scope="module")
def portal_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)],
        env=env,
        check=True,
    )
    _psql("SELECT portal.sp_security_meta_refresh_cache()", env)
    return env


def _insert_user(env: dict[str, str], full_name: str, email: str) -> int:
    return int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('{full_name.replace("'", "''")}', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )


def _create_org_admin(env: dict[str, str], label: str) -> dict[str, int | str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"{label}-{suffix}@t.test"
    user_id = _insert_user(env, f"{label} admin", email)
    created = _psql(
        f"SELECT organization_id, scope_id FROM portal.sp_organization_create('{label}-{suffix}')",
        env,
    )
    org_id_text, scope_id_text = created.split("|")
    org_id, scope_id = int(org_id_text), int(scope_id_text)
    psql = lambda sql: _psql(sql, env)  # noqa: E731
    grant_organization_admin(psql, org_id, user_id)
    token = open_session_token(psql, user_id, scope_id=scope_id)
    return {
        "user_id": user_id,
        "org_id": org_id,
        "scope_id": scope_id,
        "email": email,
        "full_name": f"{label} admin",
        "token": token,
    }


def _user_snapshot(conn: psycopg.Connection) -> list[tuple[int, str, str, int]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT "ID", "FullName", email, "Active"
            FROM "RBAC"."Users"
            ORDER BY "ID"
            """
        )
        return [(int(r[0]), str(r[1]), str(r[2]), int(r[3])) for r in cur.fetchall()]


def _member_ids(conn: psycopg.Connection, org_id: int) -> set[int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT "UserID"
            FROM portal."OrganizationMembers"
            WHERE "OrganizationID" = %s
            ORDER BY "UserID"
            """,
            (org_id,),
        )
        return {int(row[0]) for row in cur.fetchall()}


def _resolved_user_id(conn: psycopg.Connection, token: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT user_id FROM portal.fn_session_resolve(%s)",
            (token,),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _touch(conn: psycopg.Connection, token: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT portal.sp_session_touch(%s)", (token,))
        row = cur.fetchone()
    return bool(row and row[0])


def _upsert(
    conn: psycopg.Connection,
    token: str,
    email: str,
    full_name: str,
    active: int,
) -> int | None:
    """Same call the security route makes after String()/Number() on the JSON body."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT user_id FROM portal.sp_session_upsert_user(%s, %s, %s, %s)",
            (token, email, full_name, active),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _attacker_can_administer(conn: psycopg.Connection, attacker: dict[str, int | str]) -> int:
    suffix = uuid.uuid4().hex[:8]
    email = f"new-{suffix}@t.test"
    user_id = _upsert(conn, str(attacker["token"]), email, f"New {suffix}", 1)
    assert user_id is not None, "organization admin could not create a user in their own organization"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT "FullName", email, "Active"
            FROM "RBAC"."Users"
            WHERE "ID" = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[2]) == 1
    assert user_id in _member_ids(conn, int(attacker["org_id"]))
    conn.commit()
    return user_id


def _session_still_live(conn: psycopg.Connection, token: str, user_id: int) -> None:
    assert _resolved_user_id(conn, token) == user_id
    assert _touch(conn, token) is True


def test_org_admin_cannot_rename_or_adopt_user_outside_organization(portal_env: dict[str, str]) -> None:
    attacker = _create_org_admin(portal_env, "atk")
    victim = _create_org_admin(portal_env, "vic")
    disguised = f"  {str(victim['email']).upper()}  "

    with _connect(portal_env) as conn:
        _attacker_can_administer(conn, attacker)
        before_users = _user_snapshot(conn)
        before_members = _member_ids(conn, int(attacker["org_id"]))
        assert int(victim["user_id"]) not in before_members
        _session_still_live(conn, str(victim["token"]), int(victim["user_id"]))

        try:
            _upsert(conn, str(attacker["token"]), disguised, "Renamed Victim", 1)
        except psycopg.Error:
            conn.rollback()

        assert _user_snapshot(conn) == before_users
        assert _member_ids(conn, int(attacker["org_id"])) == before_members
        _session_still_live(conn, str(victim["token"]), int(victim["user_id"]))


def test_org_admin_cannot_deactivate_foreign_admin_or_platform_owner(
    portal_env: dict[str, str],
) -> None:
    attacker = _create_org_admin(portal_env, "lock")
    foreign_admin = _create_org_admin(portal_env, "peer")
    owner = _create_org_admin(portal_env, "own")
    _psql(
        f"SELECT portal.sp_security_meta_grant_god_architect_to_user({int(owner['user_id'])})",
        portal_env,
    )

    with _connect(portal_env) as conn:
        _attacker_can_administer(conn, attacker)
        before_users = _user_snapshot(conn)
        before_members = _member_ids(conn, int(attacker["org_id"]))
        assert int(foreign_admin["user_id"]) not in before_members
        assert int(owner["user_id"]) not in before_members

        for target, label in ((foreign_admin, "Taken Admin"), (owner, "Taken Owner")):
            try:
                _upsert(
                    conn,
                    str(attacker["token"]),
                    f"  {str(target['email']).upper()}  ",
                    label,
                    0,
                )
            except psycopg.Error:
                conn.rollback()

        assert _user_snapshot(conn) == before_users
        assert _member_ids(conn, int(attacker["org_id"])) == before_members
        _session_still_live(conn, str(foreign_admin["token"]), int(foreign_admin["user_id"]))
        _session_still_live(conn, str(owner["token"]), int(owner["user_id"]))


def test_org_admin_cannot_clear_global_active_flag(portal_env: dict[str, str]) -> None:
    attacker = _create_org_admin(portal_env, "home")
    member_email = f"mem-{uuid.uuid4().hex[:8]}@t.test"

    with _connect(portal_env) as conn:
        member_id = _upsert(conn, str(attacker["token"]), member_email, "Home Member", 1)
        assert member_id is not None
        conn.commit()
        psql = lambda sql: _psql(sql, portal_env)  # noqa: E731
        member_token = open_session_token(psql, member_id, scope_id=int(attacker["scope_id"]))
        _session_still_live(conn, member_token, member_id)

        # Also a person who belongs to the caller and to another organization.
        shared = _create_org_admin(portal_env, "both")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT inserted FROM portal.sp_organization_add_member(%s, %s)",
                (int(attacker["org_id"]), int(shared["user_id"])),
            )
        conn.commit()
        active_before = {
            row[0]: row[3] for row in _user_snapshot(conn)
        }

        for email, new_name in (
            (member_email, "Home Member Renamed"),
            (f"  {str(shared['email']).upper()}  ", "Shared Renamed"),
        ):
            try:
                _upsert(conn, str(attacker["token"]), email, new_name, 0)
            except psycopg.Error:
                conn.rollback()

        active_after = {row[0]: row[3] for row in _user_snapshot(conn)}
        assert active_after == active_before
        _session_still_live(conn, member_token, member_id)
        _session_still_live(conn, str(shared["token"]), int(shared["user_id"]))


def test_new_user_is_not_created_inactive(portal_env: dict[str, str]) -> None:
    attacker = _create_org_admin(portal_env, "make")
    email = f"off-{uuid.uuid4().hex[:8]}@t.test"

    with _connect(portal_env) as conn:
        _attacker_can_administer(conn, attacker)
        before_ids = {row[0] for row in _user_snapshot(conn)}
        try:
            created = _upsert(conn, str(attacker["token"]), email, "Should Stay Active", 0)
        except psycopg.Error:
            conn.rollback()
            created = None

        rows = _user_snapshot(conn)
        if created is None:
            assert {row[0] for row in rows} == before_ids
            assert all(row[2] != email for row in rows)
        else:
            match = [row for row in rows if row[0] == created]
            assert match, "upsert returned a user id that was not stored"
            assert match[0][3] == 1
            assert match[0][2] == email
            assert created in _member_ids(conn, int(attacker["org_id"]))


def test_user_without_security_admin_cannot_upsert(portal_env: dict[str, str]) -> None:
    victim = _create_org_admin(portal_env, "safe")
    caller_id = _insert_user(portal_env, "Plain Member", f"plain-{uuid.uuid4().hex[:8]}@t.test")
    org = _create_org_admin(portal_env, "host")
    _psql(
        f"SELECT inserted FROM portal.sp_organization_add_member({int(org['org_id'])}, {caller_id})",
        portal_env,
    )
    psql = lambda sql: _psql(sql, portal_env)  # noqa: E731
    token = open_session_token(psql, caller_id, scope_id=int(org["scope_id"]))

    with _connect(portal_env) as conn:
        before_users = _user_snapshot(conn)
        before_members = _member_ids(conn, int(org["org_id"]))
        with pytest.raises(psycopg.Error):
            _upsert(conn, token, str(victim["email"]), "Should Not Apply", 0)
        conn.rollback()
        assert _user_snapshot(conn) == before_users
        assert _member_ids(conn, int(org["org_id"])) == before_members
        _session_still_live(conn, str(victim["token"]), int(victim["user_id"]))
