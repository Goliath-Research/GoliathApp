"""Round-trip tests for goliath_app.portal.PortalClient (goliath_portal role)."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

from goliath_app.portal import PortalClient, PortalSemanticError
from goliath_app.portal.connection import build_portal_conninfo
from goliath_app.semantic.models import FilterOrganizationsParams, ListOrganizationsParams

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
SEED_SEMANTIC = SQL_PG / "seed_semantic_catalog.py"
PORTAL_TEST_PASSWORD = "portal_client_test_pw"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    if env.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "methyl"))
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


def _create_user(env: dict[str, str]) -> int:
    email = f"portal-client-{uuid.uuid4().hex[:8]}@test"
    return int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Portal Client User', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )


def _create_org(env: dict[str, str], user_id: int, name: str) -> int:
    escaped = name.replace("'", "''")
    row = _psql(
        f"SELECT * FROM portal.sp_organization_create('{escaped}')",
        env,
    )
    org_id = int(row.split("|")[0])
    _psql(
        f"SELECT inserted FROM portal.sp_organization_add_member({org_id}, {user_id})",
        env,
    )
    return org_id


@pytest.fixture(scope="module")
def portal_client_env() -> dict[str, str]:
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
    subprocess.run(["python3", str(SEED_SEMANTIC)], env=env, check=True)
    escaped = PORTAL_TEST_PASSWORD.replace("'", "''")
    _psql(
        f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'",
        env,
    )
    return env


@pytest.fixture(scope="module")
def portal_client(portal_client_env: dict[str, str]) -> PortalClient:
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    os.environ.setdefault("PGHOST", portal_client_env["PGHOST"])
    os.environ.setdefault("PGPORT", portal_client_env["PGPORT"])
    os.environ.setdefault("PGDATABASE", portal_client_env["PGDATABASE"])
    conninfo = build_portal_conninfo()
    return PortalClient(conninfo)


def test_session_and_semantic_round_trip(
    portal_client: PortalClient,
    portal_client_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_client_env)
    org_name = f"PortalRoundTrip-{user_id}"
    _create_org(portal_client_env, user_id, org_name)

    opened = portal_client.session_open(user_id)
    assert opened.session_token
    assert portal_client.session_touch(opened.session_token)

    catalog = portal_client.list_semantic_catalog(opened.session_token)
    codes = {entry.request_code for entry in catalog}
    assert "core.list_organizations" in codes
    assert "core.filter_organizations" in codes

    listed = portal_client.list_organizations(
        opened.session_token,
        ListOrganizationsParams(organization_id=None, limit=10),
    )
    assert any(row.name == org_name for row in listed)

    filtered = portal_client.filter_organizations(
        opened.session_token,
        FilterOrganizationsParams(name=org_name[:10]),
    )
    assert len(filtered) >= 1
    assert filtered[0].name.startswith(org_name[:10])

    assert portal_client.session_revoke(opened.session_token)
    with pytest.raises(PortalSemanticError) as excinfo:
        portal_client.list_organizations(opened.session_token)
    assert excinfo.value.code == "GS401"


def test_permission_denied_via_client(portal_client: PortalClient, portal_client_env: dict[str, str]) -> None:
    user_id = _create_user(portal_client_env)
    opened = portal_client.session_open(user_id)
    with pytest.raises(PortalSemanticError) as excinfo:
        portal_client.run_semantic_request(
            opened.session_token,
            "core.restricted_probe",
            ListOrganizationsParams(),
        )
    assert excinfo.value.code == "GS403"
