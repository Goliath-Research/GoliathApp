"""Platform security Meta classes, migration, and grant cache."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest

from goliath_app.portal.connection import build_portal_conninfo

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
PORTAL_TEST_PASSWORD = "platform_security_meta_test_pw"


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
def sec_meta_env() -> dict[str, str]:
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


def test_security_meta_classes_exist(sec_meta_env: dict[str, str]) -> None:
    names = _psql(
        """
        SELECT string_agg(c."Name", ',' ORDER BY c."Name")
        FROM "Meta"."Classes" c
        WHERE c."Name" LIKE 'platform/%'
          AND c."Name" IN (
            'platform/User', 'platform/Role', 'platform/Permission',
            'platform/RoleGrant', 'platform/ExternalIdentity', 'platform/Invitation'
          )
        """,
        sec_meta_env,
    )
    assert "platform/User" in names
    assert "platform/RoleGrant" in names


def test_grant_cache_matches_rbac_after_migrate(sec_meta_env: dict[str, str]) -> None:
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    email = f"meta-sec-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Meta Sec', '{email}', 1)
            RETURNING "ID"
            """,
            sec_meta_env,
        )
    )
    org = _psql(f"SELECT * FROM portal.sp_organization_create('MetaSec-{user_id}')", sec_meta_env)
    org_id, scope_id = (int(x) for x in org.split("|"))
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {user_id})", sec_meta_env)

    _psql("SELECT portal.sp_security_meta_migrate_from_legacy()", sec_meta_env)
    _psql("SELECT portal.sp_security_meta_refresh_cache()", sec_meta_env)

    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        meta_rows = conn.execute(
            "SELECT count(*) FROM portal.mv_security_effective_grants WHERE user_id = %s AND scope_id = %s",
            (user_id, scope_id),
        ).fetchone()
        assert meta_rows is not None and int(meta_rows[0]) >= 1

    rbac_grants = int(
        _psql(
            f"""
            SELECT COUNT(*) FROM "RBAC"."UserRoleGrants"
            WHERE "UserID" = {user_id} AND "ScopeID" = {scope_id}
              AND "Active" AND "RevokedAtUtc" IS NULL
            """,
            sec_meta_env,
        )
    )
    cache_grants = int(
        _psql(
            f"""
            SELECT COUNT(*) FROM portal.security_grant_cache
            WHERE user_id = {user_id} AND scope_id = {scope_id}
              AND active AND revoked_at_utc IS NULL
            """,
            sec_meta_env,
        )
    )
    assert cache_grants == rbac_grants

    map_line = _psql(
        f"""
        SELECT meta_obj_id FROM portal.security_meta_legacy_map
        WHERE legacy_kind = 'user' AND legacy_id = {user_id}
        """,
        sec_meta_env,
    )
    assert map_line
    assert int(map_line) > 0


def test_grant_cache_stable_on_re_migrate(sec_meta_env: dict[str, str]) -> None:
    _psql("SELECT portal.sp_security_meta_migrate_from_legacy()", sec_meta_env)
    _psql("SELECT portal.sp_security_meta_refresh_cache()", sec_meta_env)
    count_first = int(_psql("SELECT COUNT(*) FROM portal.security_grant_cache", sec_meta_env))
    _psql("SELECT portal.sp_security_meta_migrate_from_legacy()", sec_meta_env)
    _psql("SELECT portal.sp_security_meta_refresh_cache()", sec_meta_env)
    count_second = int(_psql("SELECT COUNT(*) FROM portal.security_grant_cache", sec_meta_env))
    assert count_second == count_first
