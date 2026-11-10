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

        map_row = conn.execute(
            "SELECT meta_obj_id FROM portal.security_meta_legacy_map WHERE legacy_kind = 'user' AND legacy_id = %s",
            (user_id,),
        ).fetchone()
        assert map_row is not None
        assert int(map_row[0]) == user_id
