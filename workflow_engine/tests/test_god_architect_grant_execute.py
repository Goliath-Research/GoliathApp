"""Non-owner logins must not mint a global god_architect grant.

These tests fail while portal.sp_security_meta_grant_god_architect_to_user is
callable without a God Architect session. They pass once that call is refused
and leaves no grant behind.

Untested siblings, because they do not insert a god_architect grant:
portal.sp_organization_set_admin (organization_admin only),
portal.sp_create_role / portal.sp_set_role_permission (no user grant),
wf.wf_ensure_worker_rbac_user (worker role only), and
Onboarding.spacceptinvitation (invitation role after a contract check).
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
# Obvious placeholder. Not a deployed credential.
CALLER_PASSWORD = "test-only-placeholder"
GRANT_FN = "portal.sp_security_meta_grant_god_architect_to_user(integer)"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    env.setdefault("PGSSLMODE", "disable")
    return env


def _psql(sql: str, env: dict[str, str], *, on_error_stop: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["psql", "-q", "-t", "-A"]
    if on_error_stop:
        cmd.extend(["-v", "ON_ERROR_STOP=1"])
    cmd.extend(["-c", sql])
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)


def _psql_ok(sql: str, env: dict[str, str]) -> str:
    proc = _psql(sql, env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def _caller_env(base: dict[str, str], role: str) -> dict[str, str]:
    env = base.copy()
    env["PGUSER"] = role
    env["PGPASSWORD"] = CALLER_PASSWORD
    return env


def _ensure_login(env: dict[str, str], role: str) -> None:
    escaped = CALLER_PASSWORD.replace("'", "''")
    _psql_ok(
        f"""
        DO $role$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
            CREATE ROLE {role} LOGIN;
          END IF;
        END
        $role$;
        ALTER ROLE {role} WITH LOGIN PASSWORD '{escaped}';
        GRANT CONNECT ON DATABASE {env['PGDATABASE']} TO {role};
        """,
        env,
    )


@pytest.fixture(scope="module")
def god_grant_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql_ok("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    _ensure_login(env, "goliath_portal")
    _ensure_login(env, "goliath_gateway")
    _ensure_login(env, "god_grant_public_caller")
    # Usage only. No explicit EXECUTE. Public execute is the privilege under test.
    _psql_ok("GRANT USAGE ON SCHEMA portal TO god_grant_public_caller", env)
    return env


def _god_holders(env: dict[str, str]) -> tuple[str, str, str]:
    rbac = _psql_ok(
        """
        SELECT COALESCE(string_agg(g."UserID"::text, ',' ORDER BY g."UserID"), '')
        FROM "RBAC"."UserRoleGrants" g
        INNER JOIN "RBAC"."Roles" r ON r."ID" = g."RoleID"
        WHERE r."Name" = 'god_architect'
          AND g."GrantType" = 'GLOBAL'
          AND g."Active"
          AND g."RevokedAtUtc" IS NULL
        """,
        env,
    )
    meta = _psql_ok(
        """
        SELECT COALESCE(string_agg(DISTINCT (ov."Data"->>'LegacyUserId'), ',' ORDER BY (ov."Data"->>'LegacyUserId')), '')
        FROM "Meta"."ObjValues" ov
        INNER JOIN "Meta"."Classes" c ON c."ID" = ov."ClassID"
        WHERE c."Name" = 'platform/RoleGrant'
          AND COALESCE(ov."Data"->>'GrantType', '') = 'GLOBAL'
          AND COALESCE((ov."Data"->>'Active')::boolean, false)
          AND (ov."Data"->>'LegacyRoleId')::int = portal.fn_god_architect_role_id()
        """,
        env,
    )
    catalog = _psql_ok(
        """
        SELECT COALESCE(string_agg(DISTINCT g.user_id::text, ',' ORDER BY g.user_id::text), '')
        FROM portal.mv_security_effective_grants g
        WHERE g.role_id = portal.fn_god_architect_role_id()
          AND COALESCE(g.bypass_scope, false)
        """,
        env,
    )
    return rbac, meta, catalog


def _fresh_user_and_scope(env: dict[str, str]) -> tuple[int, int, int]:
    email = f"god-grant-{uuid.uuid4().hex[:12]}@test"
    user_id = int(
        _psql_ok(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('God Grant Target', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )
    org = _psql_ok(f"SELECT organization_id, scope_id FROM portal.sp_organization_create('GodGrant {user_id}')", env)
    _org_id, scope_id = (int(part) for part in org.split("|"))
    god_role = int(_psql_ok("SELECT portal.fn_god_architect_role_id()", env))
    return user_id, scope_id, god_role


def _assert_no_new_god_grant(env: dict[str, str], before: tuple[str, str, str], caller: str, detail: str) -> None:
    after = _god_holders(env)
    assert after == before, (
        f"{caller} changed global god_architect holders ({detail}). before={before} after={after}"
    )


def _direct_insert_denied(caller_env: dict[str, str], user_id: int, god_role: int) -> None:
    proc = _psql(
        f"""
        INSERT INTO "RBAC"."UserRoleGrants"
          ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
        VALUES ({user_id}, {god_role}, 'GLOBAL', NULL, true, now())
        """,
        caller_env,
        on_error_stop=False,
    )
    assert proc.returncode != 0, f"{caller_env['PGUSER']} inserted a god_architect grant directly"


def _session_owner_check_denied(caller_env: dict[str, str], user_id: int, scope_id: int, god_role: int) -> None:
    proc = _psql(
        f"""
        DO $check$
        DECLARE
          v_token text;
          v_role int;
        BEGIN
          SELECT session_token INTO v_token
          FROM portal.sp_session_open({user_id}, {scope_id});

          BEGIN
            SELECT s.role_id INTO v_role
            FROM portal.sp_session_set_active_role(v_token, {god_role}) s;
            RAISE EXCEPTION 'god architect role was selectable';
          EXCEPTION
            WHEN OTHERS THEN
              IF SQLERRM LIKE '%god architect role was selectable%' THEN
                RAISE;
              END IF;
          END;

          BEGIN
            PERFORM 1 FROM portal.fn_session_assert_god_architect(v_token);
            RAISE EXCEPTION 'platform owner check passed';
          EXCEPTION
            WHEN OTHERS THEN
              IF SQLERRM LIKE '%platform owner check passed%' THEN
                RAISE;
              END IF;
          END;
        END
        $check$;
        """,
        caller_env,
        on_error_stop=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def _assert_caller_cannot_mint_god_architect(owner_env: dict[str, str], role: str) -> None:
    user_id, scope_id, god_role = _fresh_user_and_scope(owner_env)
    caller_env = _caller_env(owner_env, role)
    before = _god_holders(owner_env)

    _direct_insert_denied(caller_env, user_id, god_role)
    _assert_no_new_god_grant(owner_env, before, role, "direct insert")

    proc = _psql(
        f"SELECT portal.sp_security_meta_grant_god_architect_to_user({user_id})",
        caller_env,
        on_error_stop=False,
    )
    _assert_no_new_god_grant(
        owner_env,
        before,
        role,
        f"call rc={proc.returncode} output={(proc.stdout or proc.stderr).strip()}",
    )
    # Sign-in is the portal application login, including when the SQL caller was someone else.
    _session_owner_check_denied(_caller_env(owner_env, "goliath_portal"), user_id, scope_id, god_role)


def test_goliath_portal_cannot_grant_god_architect(god_grant_env: dict[str, str]) -> None:
    _assert_caller_cannot_mint_god_architect(god_grant_env, "goliath_portal")


def test_public_execute_with_portal_usage_cannot_grant_god_architect(god_grant_env: dict[str, str]) -> None:
    explicit = _psql_ok(
        f"""
        SELECT EXISTS (
          SELECT 1
          FROM aclexplode(p.proacl) a
          WHERE a.privilege_type = 'EXECUTE'
            AND a.grantee <> 0
            AND pg_get_userbyid(a.grantee) = 'god_grant_public_caller'
        )
        FROM pg_proc p
        INNER JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'portal'
          AND p.oid = '{GRANT_FN}'::regprocedure
        """,
        god_grant_env,
    )
    assert explicit == "f"
    _assert_caller_cannot_mint_god_architect(god_grant_env, "god_grant_public_caller")


def test_goliath_gateway_cannot_grant_god_architect(god_grant_env: dict[str, str]) -> None:
    _assert_caller_cannot_mint_god_architect(god_grant_env, "goliath_gateway")


def test_sp_grant_user_role_cannot_mint_god_architect(god_grant_env: dict[str, str]) -> None:
    user_id, _scope_id, god_role = _fresh_user_and_scope(god_grant_env)
    before = _god_holders(god_grant_env)
    proc = _psql(
        f"SELECT inserted, grant_id FROM portal.sp_grant_user_role({user_id}, {god_role}, 'GLOBAL', NULL, NULL)",
        _caller_env(god_grant_env, "goliath_portal"),
        on_error_stop=False,
    )
    assert proc.returncode != 0
    _assert_no_new_god_grant(god_grant_env, before, "goliath_portal", "sp_grant_user_role")


def test_session_grant_without_god_session_cannot_mint_god_architect(god_grant_env: dict[str, str]) -> None:
    user_id, _scope_id, god_role = _fresh_user_and_scope(god_grant_env)
    before = _god_holders(god_grant_env)
    proc = _psql(
        f"""
        SELECT inserted, grant_id
        FROM portal.sp_session_grant_user_role_scoped('not-a-session', {user_id}, {god_role})
        """,
        _caller_env(god_grant_env, "goliath_portal"),
        on_error_stop=False,
    )
    assert proc.returncode != 0
    _assert_no_new_god_grant(god_grant_env, before, "goliath_portal", "sp_session_grant_user_role_scoped")
