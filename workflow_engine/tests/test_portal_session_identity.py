"""External identity login contract (portal.sp_session_open_for_scope_identity)."""

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
PORTAL_TEST_PASSWORD = "portal_identity_test_pw"


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
def portal_identity_env() -> dict[str, str]:
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


def _seed_oidc_identity(env: dict[str, str], *, issuer: str, subject: str, scope_id: int) -> int:
    email = f"oidc-{uuid.uuid4().hex[:8]}@example.com"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('OIDC User', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )
    provider_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."IdentityProviders" ("Name","ProviderType","Issuer","Active","CreatedAtUtc")
            VALUES ('test-oidc', 'oidc', '{issuer.replace("'", "''")}', true, now() AT TIME ZONE 'utc')
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
    _psql(
        f"""
        INSERT INTO "RBAC"."ExternalIdentities"
          ("UserID","ProviderID","Subject","EmailSnapshot","Active","CreatedAtUtc","LastLoginAtUtc")
        VALUES ({user_id}, {provider_id}, '{subject.replace("'", "''")}', '{email}', true,
                now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc')
        """,
        env,
    )
    return user_id


def test_session_open_for_scope_identity_success(portal_identity_env: dict[str, str]) -> None:
    env = portal_identity_env
    org = _psql("SELECT * FROM portal.sp_organization_create('IdpOrg')", env)
    scope_id = int(org.split("|")[1])
    issuer = "https://login.fixture.example/"
    subject = f"sub-{uuid.uuid4().hex[:12]}"
    user_id = _seed_oidc_identity(env, issuer=issuer, subject=subject, scope_id=scope_id)
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        cur = conn.execute(
            """
            SELECT session_token, user_id
            FROM portal.sp_session_open_for_scope_identity(%s, %s, %s, %s)
            """,
            (scope_id, issuer, subject, '{"sub":"snap"}'),
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[1]) == user_id
    assert str(row[0])


def test_session_open_denies_unlinked_subject(portal_identity_env: dict[str, str]) -> None:
    env = portal_identity_env
    org = _psql("SELECT * FROM portal.sp_organization_create('IdpDeny')", env)
    scope_id = int(org.split("|")[1])
    issuer = "https://login.fixture.example/"
    _seed_oidc_identity(env, issuer=issuer, subject="linked-sub", scope_id=scope_id)
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    conninfo = build_portal_conninfo()
    with pytest.raises(psycopg.Error) as excinfo:
        with psycopg.connect(conninfo) as conn:
            conn.execute(
                """
                SELECT session_token FROM portal.sp_session_open_for_scope_identity(%s, %s, %s, NULL)
                """,
                (scope_id, issuer, "unknown-subject"),
            )
    assert "GS403" in str(excinfo.value)


def test_session_open_denies_wrong_scope_for_provider(portal_identity_env: dict[str, str]) -> None:
    env = portal_identity_env
    org_a = _psql("SELECT * FROM portal.sp_organization_create('ScopeA')", env)
    scope_a = int(org_a.split("|")[1])
    org_b = _psql("SELECT * FROM portal.sp_organization_create('ScopeB')", env)
    scope_b = int(org_b.split("|")[1])
    issuer = "https://login.fixture.example/"
    subject = f"scoped-{uuid.uuid4().hex[:8]}"
    _seed_oidc_identity(env, issuer=issuer, subject=subject, scope_id=scope_a)
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    conninfo = build_portal_conninfo()
    with pytest.raises(psycopg.Error) as excinfo:
        with psycopg.connect(conninfo) as conn:
            conn.execute(
                "SELECT session_token FROM portal.sp_session_open_for_scope_identity(%s, %s, %s, NULL)",
                (scope_b, issuer, subject),
            )
    assert "GS403" in str(excinfo.value) or "not configured" in str(excinfo.value).lower()
