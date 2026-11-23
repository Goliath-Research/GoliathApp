"""Organization administrators must not receive another tenant's scope directory.

The Scopes page (``/app/admin/scopes``) loads
``portal.sp_session_list_scopes`` through the platform query in
``apps/platform-host/src/lib/portal-platform-queries.ts``. The session function
only checks that the caller can open that page, then returns every scope.

These tests are the intended behavior and fail while that leak remains:

- The caller's active scope is returned.
- Inactive scopes of that same organization are returned only when the caller
  holds ``organization_admin`` on it and ``p_include_inactive`` is true.
- Every other scope is omitted: other organizations, other active scopes of the
  same organization, and independent-user scopes (the only rows that store
  ``owner_user_id``).
- A session that cannot open the Scopes page is rejected and the scope table
  is unchanged.

Not covered here, because they are different operations: ``portal.sp_session_org_list``,
``portal.sp_session_list_invitations``, ``portal.sp_session_list_users``,
``portal.sp_get_scope``, and a god_architect session. ``portal.sp_list_scopes``
is not called by the Scopes page.
"""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from goliath_app.portal.connection import build_portal_conninfo

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"
QUERIES = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "platform-host"
    / "src"
    / "lib"
    / "portal-platform-queries.ts"
)
SCOPES_PAGE = "/app/admin/scopes"
# Local login password this module assigns to goliath_portal. Not a deployed secret.
PORTAL_PLACEHOLDER_PASSWORD = "placeholder"


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


def _scopes_page_sql() -> str:
    """SQL the Scopes page runs.

    The platform host binds ``$1`` with node-postgres. psycopg binds ``%s`` and
    sends the same server-side statement.
    """
    text = QUERIES.read_text(encoding="utf-8")
    match = re.search(r"scopes:\s*\{.*?sql:\s*`([^`]+)`", text, re.DOTALL)
    if match is None:
        raise AssertionError(f"scopes query missing from {QUERIES}")
    sql = match.group(1).strip()
    if not re.search(r"portal\.sp_session_list_scopes\s*\(\s*\$1\s*,\s*false\s*\)", sql):
        raise AssertionError(f"scopes page no longer calls portal.sp_session_list_scopes($1, false): {sql}")
    return re.sub(r"\$\d+", "%s", sql)


@dataclass(frozen=True)
class ScopeRow:
    scope_id: int
    scope_type: str
    name: str
    organization_id: int | None
    owner_user_id: int | None
    active: bool

    @classmethod
    def from_record(cls, row: dict) -> ScopeRow:
        return cls(
            scope_id=int(row["scope_id"]),
            scope_type=str(row["scope_type"]),
            name=str(row["name"]),
            organization_id=None if row["organization_id"] is None else int(row["organization_id"]),
            owner_user_id=None if row["owner_user_id"] is None else int(row["owner_user_id"]),
            active=bool(row["active"]),
        )


@dataclass(frozen=True)
class World:
    env: dict[str, str]
    caller_org_id: int
    caller_scope_id: int
    caller_other_active_scope_id: int
    caller_inactive_scope_id: int
    victim_org_id: int
    victim_scope_id: int
    victim_inactive_scope_id: int
    victim_org_name: str
    independent_scope_id: int
    independent_owner_user_id: int
    independent_scope_name: str
    admin_token: str
    reader_token: str
    denied_token: str


def _insert_scope(
    env: dict[str, str],
    *,
    scope_type: str,
    name: str,
    organization_id: int | None,
    owner_user_id: int | None,
    active: bool,
) -> int:
    org_sql = "NULL" if organization_id is None else str(organization_id)
    owner_sql = "NULL" if owner_user_id is None else str(owner_user_id)
    escaped = name.replace("'", "''")
    return int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Scopes"
              ("ScopeType", "Name", "OrganizationID", "OwnerUserID", "Active", "CreatedAtUtc")
            VALUES (
              '{scope_type}', '{escaped}', {org_sql}, {owner_sql},
              {'true' if active else 'false'}, now()
            )
            RETURNING "ScopeID"
            """,
            env,
        )
    )


def _insert_user(env: dict[str, str], name: str) -> int:
    email = f"{name[:12]}-{uuid.uuid4().hex[:8]}@t.test"
    escaped_name = name.replace("'", "''")
    return int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('{escaped_name}', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )


def _super(env: dict[str, str]) -> psycopg.Connection:
    return psycopg.connect(
        host=env["PGHOST"],
        port=env["PGPORT"],
        dbname=env["PGDATABASE"],
        user=env["PGUSER"],
        password=env["PGPASSWORD"],
        row_factory=dict_row,
    )


def _open_token(env: dict[str, str], user_id: int, scope_id: int) -> str:
    with _super(env) as conn:
        opened = conn.execute(
            "SELECT session_token FROM portal.sp_session_open(%s, %s)",
            (user_id, scope_id),
        ).fetchone()
        if opened is None or not opened["session_token"]:
            raise RuntimeError("session did not open")
        token = str(opened["session_token"])
        selected = conn.execute(
            "SELECT role_id FROM portal.sp_session_auto_select_active_role(%s)",
            (token,),
        ).fetchone()
        conn.commit()
    if selected is None or selected["role_id"] is None:
        raise RuntimeError("session did not select its only role")
    return token


def _portal(env: dict[str, str]):
    os.environ["PGHOST"] = env["PGHOST"]
    os.environ["PGPORT"] = env["PGPORT"]
    os.environ["PGDATABASE"] = env["PGDATABASE"]
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_PLACEHOLDER_PASSWORD
    return psycopg.connect(build_portal_conninfo(), row_factory=dict_row)


def _fetch_scopes(conn: psycopg.Connection, sql: str, params: tuple) -> list[ScopeRow]:
    rows = conn.execute(sql, params).fetchall()
    return [ScopeRow.from_record(row) for row in rows]


def _assert_scope_directory(rows: list[ScopeRow], world: World, *, include_inactive: bool, administers: bool) -> None:
    allowed_ids = {world.caller_scope_id}
    if include_inactive and administers:
        allowed_ids.add(world.caller_inactive_scope_id)

    got = {row.scope_id: row for row in rows}
    leaked = [row for row in rows if row.scope_id not in allowed_ids]
    assert leaked == [], (
        "scope list returned rows outside the session's active scope "
        f"(include_inactive={include_inactive}, administers={administers}): "
        + ", ".join(
            f"id={row.scope_id} type={row.scope_type} name={row.name!r} "
            f"organization_id={row.organization_id} owner_user_id={row.owner_user_id} active={row.active}"
            for row in leaked
        )
    )
    assert world.caller_scope_id in got, "session active scope was omitted"
    caller = got[world.caller_scope_id]
    assert caller.organization_id == world.caller_org_id
    assert caller.owner_user_id is None
    assert caller.active is True

    if include_inactive and administers:
        assert world.caller_inactive_scope_id in got, "inactive scope of the administered organization was omitted"
        inactive = got[world.caller_inactive_scope_id]
        assert inactive.organization_id == world.caller_org_id
        assert inactive.active is False
    else:
        assert world.caller_inactive_scope_id not in got

    assert world.victim_scope_id not in got
    assert world.victim_inactive_scope_id not in got
    assert world.caller_other_active_scope_id not in got
    assert world.independent_scope_id not in got
    assert world.victim_org_name not in {row.name for row in rows}
    assert world.victim_org_id not in {row.organization_id for row in rows}
    assert world.independent_owner_user_id not in {row.owner_user_id for row in rows}
    assert world.independent_scope_name not in {row.name for row in rows}


@pytest.fixture(scope="module")
def world() -> World:
    from shutil import which

    if which("psql") is None:
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")

    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    escaped = PORTAL_PLACEHOLDER_PASSWORD.replace("'", "''")
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'", env)
    subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)],
        env=env,
        check=True,
    )

    suffix = uuid.uuid4().hex[:8]
    caller_name = f"CallerOrg-{suffix}"
    victim_name = f"VictimOrg-{suffix}"
    caller_org = _psql(f"SELECT * FROM portal.sp_organization_create('{caller_name}')", env)
    victim_org = _psql(f"SELECT * FROM portal.sp_organization_create('{victim_name}')", env)
    caller_org_id, caller_scope_id = (int(part) for part in caller_org.split("|"))
    victim_org_id, victim_scope_id = (int(part) for part in victim_org.split("|"))

    admin_id = _insert_user(env, "ScopeAdmin")
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({caller_org_id}, {admin_id})", env)
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({victim_org_id}, {admin_id})", env)

    caller_other_active_scope_id = _insert_scope(
        env,
        scope_type="organization",
        name=f"CallerOtherActive-{suffix}",
        organization_id=caller_org_id,
        owner_user_id=None,
        active=True,
    )
    caller_inactive_scope_id = _insert_scope(
        env,
        scope_type="organization",
        name=f"CallerInactive-{suffix}",
        organization_id=caller_org_id,
        owner_user_id=None,
        active=False,
    )
    victim_inactive_scope_id = _insert_scope(
        env,
        scope_type="organization",
        name=f"VictimInactive-{suffix}",
        organization_id=victim_org_id,
        owner_user_id=None,
        active=False,
    )
    independent_owner_user_id = _insert_user(env, "OtherOwner")
    independent_scope_name = f"Independent-{suffix}"
    independent_scope_id = _insert_scope(
        env,
        scope_type="INDEPENDENT_USER",
        name=independent_scope_name,
        organization_id=None,
        owner_user_id=independent_owner_user_id,
        active=True,
    )

    # Population path: organization_admin receives the baseline nav grant, including Scopes.
    subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)],
        env=env,
        check=True,
    )

    scopes_node_id = int(
        _psql(
            f"""SELECT "ID" FROM portal."NavTree" WHERE "NodePath" = '{SCOPES_PAGE}'""",
            env,
        )
    )
    reader_id = _insert_user(env, "ScopeReader")
    reader_role_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
            VALUES ('scope_page_reader_{suffix}', false)
            RETURNING "ID"
            """,
            env,
        )
    )
    _psql(
        f"SELECT inserted FROM portal.sp_grant_user_role({reader_id}, {reader_role_id}, 'SCOPED', {caller_scope_id}, NULL)",
        env,
    )
    _psql(
        f"SELECT ok FROM portal.sp_grant_role_nav_node({reader_role_id}, {scopes_node_id}, {caller_scope_id})",
        env,
    )

    denied_id = _insert_user(env, "NoScopes")
    denied_role_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
            VALUES ('scope_page_denied_{suffix}', false)
            RETURNING "ID"
            """,
            env,
        )
    )
    _psql(
        f"SELECT inserted FROM portal.sp_grant_user_role({denied_id}, {denied_role_id}, 'SCOPED', {caller_scope_id}, NULL)",
        env,
    )

    return World(
        env=env,
        caller_org_id=caller_org_id,
        caller_scope_id=caller_scope_id,
        caller_other_active_scope_id=caller_other_active_scope_id,
        caller_inactive_scope_id=caller_inactive_scope_id,
        victim_org_id=victim_org_id,
        victim_scope_id=victim_scope_id,
        victim_inactive_scope_id=victim_inactive_scope_id,
        victim_org_name=victim_name,
        independent_scope_id=independent_scope_id,
        independent_owner_user_id=independent_owner_user_id,
        independent_scope_name=independent_scope_name,
        admin_token=_open_token(env, admin_id, caller_scope_id),
        reader_token=_open_token(env, reader_id, caller_scope_id),
        denied_token=_open_token(env, denied_id, caller_scope_id),
    )


def _require_scopes_page(conn: psycopg.Connection, token: str) -> None:
    rows = conn.execute(
        "SELECT node_path FROM portal.sp_session_operator_nav_tree(%s) WHERE node_path = %s",
        (token, SCOPES_PAGE),
    ).fetchall()
    assert rows, "session cannot open the Scopes page, so this is not the reported path"


def test_scopes_page_query_hides_other_organizations(world: World) -> None:
    """Attack path: organization admin opens Scopes; the page query passes include_inactive false."""
    page_sql = _scopes_page_sql()
    with _portal(world.env) as conn:
        _require_scopes_page(conn, world.admin_token)
        page_rows = _fetch_scopes(conn, page_sql, (world.admin_token,))
        function_rows = _fetch_scopes(
            conn,
            "SELECT * FROM portal.sp_session_list_scopes(%s, false)",
            (world.admin_token,),
        )
    assert [(row.scope_id, row.organization_id, row.owner_user_id, row.name) for row in page_rows] == [
        (row.scope_id, row.organization_id, row.owner_user_id, row.name) for row in function_rows
    ]
    _assert_scope_directory(page_rows, world, include_inactive=False, administers=True)


def test_session_list_scopes_inactive_stays_in_administered_organization(world: World) -> None:
    """Same function with include_inactive true: inactive rows of the active organization only."""
    with _portal(world.env) as conn:
        _require_scopes_page(conn, world.admin_token)
        rows = _fetch_scopes(
            conn,
            "SELECT * FROM portal.sp_session_list_scopes(%s, true)",
            (world.admin_token,),
        )
    _assert_scope_directory(rows, world, include_inactive=True, administers=True)


def test_scopes_reader_without_admin_sees_only_the_active_scope(world: World) -> None:
    """A role that can open Scopes but is not organization_admin does not receive inactive scopes."""
    page_sql = _scopes_page_sql()
    with _portal(world.env) as conn:
        _require_scopes_page(conn, world.reader_token)
        page_rows = _fetch_scopes(conn, page_sql, (world.reader_token,))
        inactive_rows = _fetch_scopes(
            conn,
            "SELECT * FROM portal.sp_session_list_scopes(%s, true)",
            (world.reader_token,),
        )
    _assert_scope_directory(page_rows, world, include_inactive=False, administers=False)
    _assert_scope_directory(inactive_rows, world, include_inactive=True, administers=False)


def test_scopes_list_without_page_grant_is_denied_without_changes(world: World) -> None:
    with _super(world.env) as setup:
        before = setup.execute('SELECT count(*) AS n FROM "RBAC"."Scopes"').fetchone()
    assert before is not None
    with _portal(world.env) as conn:
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(
                "SELECT * FROM portal.sp_session_list_scopes(%s, true)",
                (world.denied_token,),
            )
    with _super(world.env) as setup:
        after = setup.execute('SELECT count(*) AS n FROM "RBAC"."Scopes"').fetchone()
    assert exc.value.sqlstate == "GS403"
    assert after == before
