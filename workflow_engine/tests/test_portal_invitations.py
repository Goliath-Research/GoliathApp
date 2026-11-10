"""Invitations, first-sign-in linking, and scoped provider resolution."""

from __future__ import annotations

import json
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
PORTAL_TEST_PASSWORD = "portal_invitation_test_pw"


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


def _seed_scope_provider(env: dict[str, str], scope_id: int, issuer: str) -> int:
    provider_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."IdentityProviders" ("Name","ProviderType","Issuer","Active","CreatedAtUtc")
            VALUES ('inv-test-{uuid.uuid4().hex[:6]}', 'oidc', '{issuer.replace("'", "''")}', true,
                    now() AT TIME ZONE 'utc')
            RETURNING "ProviderID"
            """,
            env,
        )
    )
    _psql(
        f"""
        INSERT INTO "RBAC"."ScopeIdentityProviders" ("ScopeID","ProviderID","Active","CreatedAtUtc")
        VALUES ({scope_id}, {provider_id}, true, now() AT TIME ZONE 'utc')
        ON CONFLICT DO NOTHING
        """,
        env,
    )
    return provider_id


def _seed_scope_contract(env: dict[str, str], org_id: int, scope_id: int, role_id: int) -> None:
    contract_id = int(
        _psql(
            f"SELECT contract_id FROM portal.sp_upsert_contract({org_id}, 'InviteTest', 'ACTIVE')",
            env,
        )
    )
    scopes_json = json.dumps([{"scope_id": scope_id, "status": "ACTIVE"}])
    _psql(
        f"SELECT 1 FROM portal.sp_set_contract_scopes({contract_id}, '{scopes_json}'::jsonb)",
        env,
    )
    _psql(
        f"""
        INSERT INTO "Contract"."ContractRolePolicies"
          ("ContractID", "RoleID", "GrantTypeAllowed", "RequiresApproval", "CreatedAtUtc")
        VALUES ({contract_id}, {role_id}, 'SCOPED', false, now() AT TIME ZONE 'utc')
        ON CONFLICT ("ContractID", "RoleID") DO NOTHING
        """,
        env,
    )


@pytest.fixture(scope="module")
def invitation_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)], env=env, check=True)
    escaped = PORTAL_TEST_PASSWORD.replace("'", "''")
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'", env)
    return env


def _admin_session(env: dict[str, str], org_name: str) -> tuple[int, int, int, str]:
    """Returns org_id, scope_id, admin_id, session_token."""
    org = _psql(f"SELECT * FROM portal.sp_organization_create('{org_name}')", env)
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    admin_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Admin', 'admin-{uuid.uuid4().hex[:8]}@test', 1) RETURNING "ID" """,
            env,
        )
    )
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {admin_id})", env)
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    client = PortalClient(build_portal_conninfo())
    token = client.session_open(admin_id, active_scope_id=scope_id).session_token
    return org_id, scope_id, admin_id, token


def _default_contract_role_id(env: dict[str, str]) -> int:
    return int(
        _psql("""SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin' LIMIT 1""", env)
    )


def test_create_invitation_resolves_provider(invitation_env: dict[str, str]) -> None:
    env = invitation_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    issuer = f"https://login.fixture.example/{uuid.uuid4().hex[:6]}/"
    org = _psql("SELECT * FROM portal.sp_organization_create('InvOrg')", env)
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    provider_id = _seed_scope_provider(env, scope_id, issuer)
    role_id = _default_contract_role_id(env)
    _seed_scope_contract(env, org_id, scope_id, role_id)
    admin_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Admin', 'admin-{uuid.uuid4().hex[:8]}@test', 1) RETURNING "ID" """,
            env,
        )
    )
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {admin_id})", env)
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    client = PortalClient(build_portal_conninfo())
    token = client.session_open(admin_id, active_scope_id=scope_id).session_token
    email = f"invitee-{uuid.uuid4().hex[:8]}@fixture.example"
    with psycopg.connect(build_portal_conninfo()) as conn:
        inv_id = conn.execute(
            "SELECT invitation_id FROM portal.sp_session_create_invitation_scoped(%s, %s, %s, NULL)",
            (token, email, role_id),
        ).fetchone()
        assert inv_id is not None
        row = conn.execute(
            """SELECT "ExpectedProviderID", "Status" FROM "Onboarding"."Invitations" WHERE "InvitationID" = %s""",
            (inv_id[0],),
        ).fetchone()
        assert row is not None
        assert int(row[0]) == provider_id
        assert row[1] == "PENDING"


def test_duplicate_pending_invitation_gs409(invitation_env: dict[str, str]) -> None:
    env = invitation_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    issuer = f"https://login.fixture.example/{uuid.uuid4().hex[:6]}/"
    org = _psql("SELECT * FROM portal.sp_organization_create('InvDup')", env)
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    _seed_scope_provider(env, scope_id, issuer)
    role_id = int(_psql("""SELECT "ID" FROM "RBAC"."Roles" ORDER BY "ID" LIMIT 1""", env))
    _seed_scope_contract(env, org_id, scope_id, role_id)
    admin_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Admin', 'admin-{uuid.uuid4().hex[:6]}@test', 1) RETURNING "ID" """,
            env,
        )
    )
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {admin_id})", env)
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID","RoleID","GrantType","ScopeID","Active","GrantedAtUtc")
            SELECT {admin_id}, p."ID", 'SCOPED', {scope_id}, true, now() AT TIME ZONE 'utc'
            FROM "RBAC"."Permissions" p WHERE p."Name" = 'platform.security.admin'""",
        env,
    )
    client = PortalClient(build_portal_conninfo())
    token = client.session_open(admin_id, active_scope_id=scope_id).session_token
    email = f"dup-{uuid.uuid4().hex[:8]}@fixture.example"
    with psycopg.connect(build_portal_conninfo()) as conn:
        conn.execute(
            "SELECT invitation_id FROM portal.sp_session_create_invitation_scoped(%s, %s, %s, NULL)",
            (token, email, role_id),
        )
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(
                "SELECT invitation_id FROM portal.sp_session_create_invitation_scoped(%s, %s, %s, NULL)",
                (token, email, role_id),
            )
        assert "GS409" in str(exc.value)


def test_no_provider_on_scope_gs403(invitation_env: dict[str, str]) -> None:
    env = invitation_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    org = _psql("SELECT * FROM portal.sp_organization_create('InvNoProv')", env)
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    role_id = int(_psql("""SELECT "ID" FROM "RBAC"."Roles" ORDER BY "ID" LIMIT 1""", env))
    _seed_scope_contract(env, org_id, scope_id, role_id)
    admin_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Admin', 'admin-{uuid.uuid4().hex[:6]}@test', 1) RETURNING "ID" """,
            env,
        )
    )
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {admin_id})", env)
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID","RoleID","GrantType","ScopeID","Active","GrantedAtUtc")
            SELECT {admin_id}, p."ID", 'SCOPED', {scope_id}, true, now() AT TIME ZONE 'utc'
            FROM "RBAC"."Permissions" p WHERE p."Name" = 'platform.security.admin'""",
        env,
    )
    client = PortalClient(build_portal_conninfo())
    token = client.session_open(admin_id, active_scope_id=scope_id).session_token
    with psycopg.connect(build_portal_conninfo()) as conn:
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(
                "SELECT invitation_id FROM portal.sp_session_create_invitation_scoped(%s, %s, %s, NULL)",
                (token, "user@fixture.example", role_id),
            )
        assert "GS403" in str(exc.value)


def test_admin_precreated_user_first_sign_in_link(invitation_env: dict[str, str]) -> None:
    env = invitation_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    issuer = f"https://login.fixture.example/{uuid.uuid4().hex[:6]}/"
    org = _psql("SELECT * FROM portal.sp_organization_create('Precreated')", env)
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    _seed_scope_provider(env, scope_id, issuer)
    email = f"precreated-{uuid.uuid4().hex[:8]}@fixture.example"
    user_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Pre User', '{email}', 1) RETURNING "ID" """,
            env,
        )
    )
    _psql(f"SELECT inserted FROM portal.sp_organization_add_member({org_id}, {user_id})", env)
    subject = f"entra-sub-{uuid.uuid4().hex[:10]}"
    snap = json.dumps({"iss": issuer, "sub": subject, "email": email, "name": "Pre User"})
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            "SELECT session_token, user_id FROM portal.sp_session_open_for_scope_identity(%s, %s, %s, %s)",
            (scope_id, issuer, subject, snap),
        ).fetchone()
        assert row is not None
        assert int(row[1]) == user_id
        audit = conn.execute(
            "SELECT COUNT(*) FROM portal.external_identity_link_audit WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        assert audit is not None and int(audit[0]) >= 1


def test_wrong_issuer_refused(invitation_env: dict[str, str]) -> None:
    env = invitation_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    issuer = f"https://login.fixture.example/{uuid.uuid4().hex[:6]}/"
    org = _psql("SELECT * FROM portal.sp_organization_create('WrongIss')", env)
    scope_id = int(org.split("|")[1])
    _seed_scope_provider(env, scope_id, issuer)
    conninfo = build_portal_conninfo()
    with pytest.raises(psycopg.Error) as excinfo:
        with psycopg.connect(conninfo) as conn:
            conn.execute(
                "SELECT session_token FROM portal.sp_session_open_for_scope_identity(%s, %s, %s, %s)",
                (scope_id, "https://wrong-tenant.example/", "sub-1", '{"email":"a@b.com"}'),
            )
    assert "GS403" in str(excinfo.value)


def test_user_cannot_link_second_subject_same_provider(invitation_env: dict[str, str]) -> None:
    env = invitation_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    issuer = f"https://login.fixture.example/{uuid.uuid4().hex[:6]}/"
    org = _psql("SELECT * FROM portal.sp_organization_create('SubLink')", env)
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    provider_id = _seed_scope_provider(env, scope_id, issuer)
    email = f"b-{uuid.uuid4().hex[:6]}@fixture.example"
    user_b = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('B', '{email}', 1) RETURNING "ID" """,
            env,
        )
    )
    _psql(f"SELECT inserted FROM portal.sp_organization_add_member({org_id}, {user_b})", env)
    _psql(
        f"""
        INSERT INTO "RBAC"."ExternalIdentities"
          ("UserID","ProviderID","Subject","EmailSnapshot","Active","CreatedAtUtc")
        VALUES ({user_b}, {provider_id}, 'existing-subject', '{email}', true, now() AT TIME ZONE 'utc')
        """,
        env,
    )
    snap = json.dumps({"email": email, "sub": "new-subject"})
    conninfo = build_portal_conninfo()
    with pytest.raises(psycopg.Error) as excinfo:
        with psycopg.connect(conninfo) as conn:
            conn.execute(
                "SELECT session_token FROM portal.sp_session_open_for_scope_identity(%s, %s, %s, %s)",
                (scope_id, issuer, "new-subject", snap),
            )
    assert "GS403" in str(excinfo.value)


def test_invitation_accept_on_first_sign_in(invitation_env: dict[str, str]) -> None:
    env = invitation_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    issuer = f"https://login.fixture.example/{uuid.uuid4().hex[:6]}/"
    org = _psql("SELECT * FROM portal.sp_organization_create('InvAccept')", env)
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    _seed_scope_provider(env, scope_id, issuer)
    role_id = int(_psql("""SELECT "ID" FROM "RBAC"."Roles" ORDER BY "ID" LIMIT 1""", env))
    _seed_scope_contract(env, org_id, scope_id, role_id)
    email = f"invite-accept-{uuid.uuid4().hex[:8]}@fixture.example"
    inv_id = int(
        _psql(
            f"""
            SELECT invitation_id FROM portal.sp_create_invitation(
              {scope_id}, '{email}',
              (SELECT sip."ProviderID" FROM "RBAC"."ScopeIdentityProviders" sip WHERE sip."ScopeID" = {scope_id} LIMIT 1),
              (now() AT TIME ZONE 'utc') + interval '7 days',
              NULL, {role_id}, 'SCOPED', NULL
            )
            """,
            env,
        )
    )
    subject = f"inv-sub-{uuid.uuid4().hex[:10]}"
    snap = json.dumps({"iss": issuer, "sub": subject, "email": email, "name": "Invited"})
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            "SELECT session_token, user_id FROM portal.sp_session_open_for_scope_identity(%s, %s, %s, %s)",
            (scope_id, issuer, subject, snap),
        ).fetchone()
        assert row is not None
        user_id = int(row[1])
        status = conn.execute(
            """SELECT "Status" FROM "Onboarding"."Invitations" WHERE "InvitationID" = %s""",
            (inv_id,),
        ).fetchone()
        assert status is not None and status[0] == "ACCEPTED"
        grant = conn.execute(
            """SELECT COUNT(*) FROM "RBAC"."UserRoleGrants"
               WHERE "UserID" = %s AND "RoleID" = %s AND "ScopeID" = %s AND "Active" """,
            (user_id, role_id, scope_id),
        ).fetchone()
        assert grant is not None and int(grant[0]) >= 1


def test_list_users_admin_roles_summary_and_revoke_grant(invitation_env: dict[str, str]) -> None:
    env = invitation_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    org = _psql("SELECT * FROM portal.sp_organization_create('RoleList')", env)
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    role_id = int(_psql("""SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin'""", env))
    _seed_scope_contract(env, org_id, scope_id, role_id)
    admin_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Admin', 'admin-{uuid.uuid4().hex[:6]}@test', 1) RETURNING "ID" """,
            env,
        )
    )
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {admin_id})", env)
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID","RoleID","GrantType","ScopeID","Active","GrantedAtUtc")
            SELECT {admin_id}, p."ID", 'SCOPED', {scope_id}, true, now() AT TIME ZONE 'utc'
            FROM "RBAC"."Permissions" p WHERE p."Name" = 'platform.security.admin'""",
        env,
    )
    member_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Member', 'member-{uuid.uuid4().hex[:6]}@test', 1) RETURNING "ID" """,
            env,
        )
    )
    _psql(f"SELECT inserted FROM portal.sp_organization_add_member({org_id}, {member_id})", env)
    grant_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."UserRoleGrants" ("UserID","RoleID","GrantType","ScopeID","Active","GrantedAtUtc")
            VALUES ({member_id}, {role_id}, 'SCOPED', {scope_id}, true, now() AT TIME ZONE 'utc')
            RETURNING "ID"
            """,
            env,
        )
    )

    client = PortalClient(build_portal_conninfo())
    token = client.session_open(admin_id, active_scope_id=scope_id).session_token
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        summary = conn.execute(
            """SELECT active_roles_summary FROM portal.sp_session_list_users_admin(%s)
               WHERE user_id = %s""",
            (token, member_id),
        ).fetchone()
        assert summary is not None
        assert "organization_admin" in summary[0]

        rows = conn.execute(
            "SELECT grant_id, role_name FROM portal.sp_session_list_user_role_grants_scoped(%s, %s)",
            (token, member_id),
        ).fetchall()
        assert len(rows) == 1

        conn.execute(
            "SELECT revoked FROM portal.sp_session_revoke_user_role_grant(%s, %s)",
            (token, grant_id),
        )
        rows_after = conn.execute(
            "SELECT grant_id FROM portal.sp_session_list_user_role_grants_scoped(%s, %s)",
            (token, member_id),
        ).fetchall()
        assert rows_after == []

    with psycopg.connect(conninfo) as conn:
        admin_grant = conn.execute(
            """SELECT g."ID" FROM "RBAC"."UserRoleGrants" g
               INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
               WHERE g."UserID" = %s AND g."ScopeID" = %s AND r."Name" = 'organization_admin'
                 AND g."Active" AND g."RevokedAtUtc" IS NULL""",
            (admin_id, scope_id),
        ).fetchone()
        assert admin_grant is not None
        with pytest.raises(psycopg.Error) as exc:
            conn.execute(
                "SELECT revoked FROM portal.sp_session_revoke_user_role_grant(%s, %s)",
                (token, admin_grant[0]),
            )
        assert "GS403" in str(exc.value)
