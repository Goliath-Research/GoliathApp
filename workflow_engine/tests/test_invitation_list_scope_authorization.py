"""Invitations page must not list another organization's invitations.

The operator Invitations page (``/app/admin/invitations``) loads
``PLATFORM_QUERY_SQL["invitations"]`` and runs that SQL as ``goliath_portal``
with the signed-in session token. These tests execute that SQL, and the same
session function with a caller-supplied scope or status, against a database
built by ``apply_schema.sh`` and ``seed_platform_nav_tree.sql``.

They describe the required behavior: rows are limited to the session's active
organization scope. They fail while a null or foreign scope still returns
other tenants.

``portal.sp_list_invitations`` and ``portal.sp_revoke_invitation`` are not
called by the invitations page. They are not covered here.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from goliath_app.portal.connection import build_portal_conninfo

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
REPO = SQL_PG.parents[1]
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"
QUERIES = REPO / "apps/platform-host/src/lib/portal-platform-queries.ts"
PORTAL_ROLE_PASSWORD = "placeholder-not-a-secret"
INVITATIONS_NAV = "/app/admin/invitations"


# node-pg placeholder text in portal-platform-queries.ts. The host binds the
# session token as the only parameter and leaves both filters null.
INVITATIONS_PAGE_SQL = "SELECT * FROM portal.sp_session_list_invitations($1, NULL, NULL)"


def invitations_page_sql() -> str:
    """SQL string the Invitations page passes to ``portalSessionPlatformQuery``."""
    text = QUERIES.read_text()
    marker = "invitations:"
    start = text.index(marker)
    sql_at = text.index("sql:", start)
    open_tick = text.index("`", sql_at)
    close_tick = text.index("`", open_tick + 1)
    sql = text[open_tick + 1 : close_tick].strip()
    assert sql == INVITATIONS_PAGE_SQL
    return sql


def _bind(sql: str) -> str:
    """psycopg uses %s; the host query uses node-pg $1 for the session token."""
    if "$1" not in sql:
        return sql
    if sql.count("$1") != 1 or "$2" in sql:
        raise AssertionError(f"expected a single session-token placeholder: {sql}")
    return sql.replace("$1", "%s")


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    env.setdefault("PGSSLMODE", "prefer")
    return env


def _super(env: dict[str, str]) -> psycopg.Connection:
    return psycopg.connect(
        host=env["PGHOST"],
        port=env["PGPORT"],
        user=env["PGUSER"],
        password=env["PGPASSWORD"],
        dbname=env["PGDATABASE"],
        autocommit=True,
    )


@pytest.fixture(scope="module")
def db_env() -> dict[str, str]:
    from shutil import which

    if which("psql") is None:
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        with _super(env) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        pytest.skip("PostgreSQL not reachable")
    applied = subprocess.run(["bash", str(APPLY_SH)], env=env, capture_output=True, text=True)
    if applied.returncode != 0:
        raise RuntimeError(applied.stderr or applied.stdout)
    with _super(env) as conn:
        conn.execute(
            sql.SQL("ALTER ROLE goliath_portal WITH LOGIN PASSWORD {}").format(
                sql.Literal(PORTAL_ROLE_PASSWORD)
            )
        )
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_ROLE_PASSWORD
    os.environ["PGHOST"] = env["PGHOST"]
    os.environ["PGPORT"] = env["PGPORT"]
    os.environ["PGDATABASE"] = env["PGDATABASE"]
    return env


def _seed_nav(env: dict[str, str]) -> None:
    seeded = subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)],
        env=env,
        capture_output=True,
        text=True,
    )
    if seeded.returncode != 0:
        raise RuntimeError(seeded.stderr or seeded.stdout)


def _insert_provider(conn: psycopg.Connection, scope_id: int) -> int:
    issuer = f"https://login.fixture.example/{uuid.uuid4().hex}/"
    provider_id = conn.execute(
        """
        INSERT INTO "RBAC"."IdentityProviders"
          ("Name", "ProviderType", "Issuer", "Active", "CreatedAtUtc")
        VALUES (%s, 'oidc', %s, true, now())
        RETURNING "ProviderID"
        """,
        (f"inv-scope-{uuid.uuid4().hex[:8]}", issuer),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO "RBAC"."ScopeIdentityProviders"
          ("ScopeID", "ProviderID", "Active", "CreatedAtUtc")
        VALUES (%s, %s, true, now())
        """,
        (scope_id, provider_id),
    )
    return int(provider_id)


def _insert_invitation(
    conn: psycopg.Connection,
    scope_id: int,
    email: str,
    provider_id: int,
    role_id: int,
    status: str,
) -> int:
    invitation_id = int(
        conn.execute(
            """
            SELECT invitation_id FROM portal.sp_create_invitation(
              %s, %s, %s, now() + interval '14 days', NULL, %s, 'SCOPED', NULL
            )
            """,
            (scope_id, email, provider_id, role_id),
        ).fetchone()[0]
    )
    if status != "PENDING":
        conn.execute(
            """
            UPDATE "Onboarding"."Invitations"
            SET "Status" = %s
            WHERE "InvitationID" = %s
            """,
            (status, invitation_id),
        )
    return invitation_id


def _insert_role(conn: psycopg.Connection, name: str) -> int:
    return int(
        conn.execute(
            """
            INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
            VALUES (%s, false)
            RETURNING "ID"
            """,
            (name,),
        ).fetchone()[0]
    )


@dataclass(frozen=True)
class OrgAdminSession:
    scope_id: int
    other_scope_id: int
    token: str
    own_email: str
    other_email: str
    own_role_id: int
    other_role_id: int
    other_accepted_email: str

    def __repr__(self) -> str:
        return (
            f"OrgAdminSession(scope_id={self.scope_id}, other_scope_id={self.other_scope_id}, "
            f"own_email={self.own_email!r}, other_email={self.other_email!r})"
        )


def _organization_admin_role_id(conn: psycopg.Connection) -> int:
    row = conn.execute(
        """
        SELECT "ID", "BypassScope"
        FROM "RBAC"."Roles"
        WHERE "Name" = 'organization_admin'
        """
    ).fetchone()
    assert row is not None
    role_id, bypass = int(row[0]), bool(row[1])
    assert bypass is False
    return role_id


def _create_org(conn: psycopg.Connection, name: str) -> tuple[int, int]:
    row = conn.execute(
        "SELECT organization_id, scope_id FROM portal.sp_organization_create(%s)",
        (name,),
    ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def _create_user(conn: psycopg.Connection, full_name: str) -> int:
    email = f"{full_name}-{uuid.uuid4().hex[:8]}@fixture.example"
    return int(
        conn.execute(
            """
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES (%s, %s, 1)
            RETURNING "ID"
            """,
            (full_name, email),
        ).fetchone()[0]
    )


def _open_session(conn: psycopg.Connection, user_id: int, scope_id: int, role_id: int | None) -> str:
    token = conn.execute(
        "SELECT session_token FROM portal.sp_session_open(%s, %s)",
        (user_id, scope_id),
    ).fetchone()[0]
    if role_id is not None:
        conn.execute(
            "SELECT role_id FROM portal.sp_session_set_active_role(%s, %s)",
            (token, role_id),
        )
    return str(token)


def _portal_rows(sql: str, params: tuple[object, ...]) -> list[dict[str, object]]:
    with psycopg.connect(build_portal_conninfo(), row_factory=dict_row) as conn:
        return list(conn.execute(_bind(sql), params).fetchall())


def _assert_only_active_scope(rows: list[dict[str, object]], session: OrgAdminSession) -> None:
    emails = {str(row["email"]) for row in rows}
    role_ids = {int(row["default_role_id"]) for row in rows if row["default_role_id"] is not None}
    scopes = {int(row["scope_id"]) for row in rows}
    assert session.own_email in emails
    assert session.other_email not in emails
    assert session.other_accepted_email not in emails
    assert session.other_role_id not in role_ids
    assert scopes == {session.scope_id}
    assert all(str(row["status"]) for row in rows)


def _org_admin_session(env: dict[str, str], *, admin_of_both: bool) -> OrgAdminSession:
    suffix = uuid.uuid4().hex[:8]
    with _super(env) as conn:
        org_a, scope_a = _create_org(conn, f"Org A {suffix}")
        org_b, scope_b = _create_org(conn, f"Org B {suffix}")
        _seed_nav(env)
        admin_role = _organization_admin_role_id(conn)
        other_role = _insert_role(conn, f"tenant_b_role_{suffix}")
        admin_id = _create_user(conn, "org-admin")
        conn.execute("SELECT grant_id FROM portal.sp_organization_set_admin(%s, %s)", (org_a, admin_id))
        if admin_of_both:
            conn.execute(
                "SELECT grant_id FROM portal.sp_organization_set_admin(%s, %s)",
                (org_b, admin_id),
            )
        provider_a = _insert_provider(conn, scope_a)
        provider_b = _insert_provider(conn, scope_b)
        own_email = f"own-{suffix}@fixture.example"
        other_email = f"other-{suffix}@fixture.example"
        other_accepted = f"accepted-{suffix}@fixture.example"
        _insert_invitation(conn, scope_a, own_email, provider_a, admin_role, "PENDING")
        _insert_invitation(conn, scope_b, other_email, provider_b, other_role, "PENDING")
        _insert_invitation(conn, scope_b, other_accepted, provider_b, other_role, "ACCEPTED")
        grants_on_b = conn.execute(
            """
            SELECT COUNT(*) FROM "RBAC"."UserRoleGrants" g
            WHERE g."UserID" = %s AND g."ScopeID" = %s AND g."Active" = true
            """,
            (admin_id, scope_b),
        ).fetchone()[0]
        assert int(grants_on_b) == (1 if admin_of_both else 0)
        token = _open_session(conn, admin_id, scope_a, None)
        visible = _portal_rows(
            """
            SELECT node_path
            FROM portal.sp_session_operator_nav_tree(%s)
            WHERE node_path = %s
            """,
            (token, INVITATIONS_NAV),
        )
        assert visible, "organization_admin session cannot open the invitations page"
    return OrgAdminSession(
        scope_id=scope_a,
        other_scope_id=scope_b,
        token=token,
        own_email=own_email,
        other_email=other_email,
        own_role_id=admin_role,
        other_role_id=other_role,
        other_accepted_email=other_accepted,
    )


def test_invitations_page_lists_only_the_active_organization(db_env: dict[str, str]) -> None:
    session = _org_admin_session(db_env, admin_of_both=False)
    rows = _portal_rows(invitations_page_sql(), (session.token,))
    _assert_only_active_scope(rows, session)
    assert any(int(row["default_role_id"]) == session.own_role_id for row in rows)
    assert any(str(row["status"]) == "PENDING" for row in rows)


def test_admin_of_two_organizations_still_sees_only_the_active_scope(db_env: dict[str, str]) -> None:
    session = _org_admin_session(db_env, admin_of_both=True)
    rows = _portal_rows(invitations_page_sql(), (session.token,))
    _assert_only_active_scope(rows, session)


def test_caller_supplied_scope_is_ignored(db_env: dict[str, str]) -> None:
    session = _org_admin_session(db_env, admin_of_both=False)
    rows = _portal_rows(
        "SELECT * FROM portal.sp_session_list_invitations(%s, %s, NULL)",
        (session.token, session.other_scope_id),
    )
    _assert_only_active_scope(rows, session)


def test_status_filter_stays_inside_the_active_scope(db_env: dict[str, str]) -> None:
    session = _org_admin_session(db_env, admin_of_both=False)
    rows = _portal_rows(
        "SELECT * FROM portal.sp_session_list_invitations(%s, NULL, %s)",
        (session.token, "PENDING"),
    )
    _assert_only_active_scope(rows, session)
    assert {str(row["status"]) for row in rows} == {"PENDING"}


def test_session_without_invitations_nav_is_denied(db_env: dict[str, str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    with _super(db_env) as conn:
        _org, scope_id = _create_org(conn, f"Reader org {suffix}")
        _seed_nav(db_env)
        reader_role = _insert_role(conn, f"scope_reader_{suffix}")
        user_id = _create_user(conn, "reader")
        conn.execute(
            """
            INSERT INTO "RBAC"."UserRoleGrants"
              ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES (%s, %s, 'SCOPED', %s, true, now())
            """,
            (user_id, reader_role, scope_id),
        )
        token = _open_session(conn, user_id, scope_id, reader_role)
        provider_id = _insert_provider(conn, scope_id)
        secret_email = f"hidden-{suffix}@fixture.example"
        _insert_invitation(conn, scope_id, secret_email, provider_id, reader_role, "PENDING")

    with pytest.raises(psycopg.Error) as raised:
        _portal_rows(invitations_page_sql(), (token,))
    assert raised.value.sqlstate == "GS403"
    message = str(raised.value).lower()
    assert "navigation" in message or "nav" in message
    assert secret_email not in message
