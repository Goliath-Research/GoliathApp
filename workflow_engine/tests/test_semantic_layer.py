"""Integration tests for semantic layer runner (A2)."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
SEED_SEMANTIC = SQL_PG / "seed_semantic_catalog.py"


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


def _psql(sql: str, env: dict[str, str], *, verbose_errors: bool = False) -> str:
    prefix = "\\set VERBOSITY verbose\n" if verbose_errors else ""
    proc = subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", prefix + sql],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def _psql_expect_error(sql: str, env: dict[str, str], errcode: str) -> str:
    proc = subprocess.run(
        [
            "psql",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "-t",
            "-A",
            "-c",
            "\\set VERBOSITY verbose\n" + sql,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0, "expected failure"
    combined = (proc.stderr or "") + (proc.stdout or "")
    assert errcode in combined
    return combined


@pytest.fixture(scope="module")
def semantic_env() -> dict[str, str]:
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
    return env


def _open_session(env: dict[str, str], user_id: int) -> str:
    row = _psql(
        f"SELECT session_token FROM portal.sp_session_open({user_id})",
        env,
    )
    return row.split("|")[0]


def _create_user(env: dict[str, str]) -> int:
    email = f"semantic-{uuid.uuid4().hex[:8]}@test"
    return int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Semantic User', '{email}', 1)
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


def test_session_denied(semantic_env: dict[str, str]) -> None:
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request('not-a-token', 'core.list_organizations')",
        semantic_env,
        "GS401",
    )


def test_cross_organization_denied(semantic_env: dict[str, str]) -> None:
    user_a = _create_user(semantic_env)
    user_b = _create_user(semantic_env)
    org_b = _create_org(semantic_env, user_b, f"OrgB-{user_b}")
    token_a = _open_session(semantic_env, user_a)
    params = json.dumps({"organization_id": org_b})
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request("
        f"'{token_a}', 'core.list_organizations', '1', '{params}'::jsonb)",
        semantic_env,
        "GS403",
    )


def test_invalid_limit_param_gs400(semantic_env: dict[str, str]) -> None:
    user_id = _create_user(semantic_env)
    _create_org(semantic_env, user_id, f"Org-{user_id}")
    token = _open_session(semantic_env, user_id)
    params = json.dumps({"limit": "not-an-integer"})
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request("
        f"'{token}', 'core.list_organizations', '1', '{params}'::jsonb)",
        semantic_env,
        "GS400",
    )


def test_missing_param_gs400(semantic_env: dict[str, str]) -> None:
    user_id = _create_user(semantic_env)
    _create_org(semantic_env, user_id, f"Org-{user_id}")
    token = _open_session(semantic_env, user_id)
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request("
        f"'{token}', 'core.filter_organizations', '1', '{{}}'::jsonb)",
        semantic_env,
        "GS400",
    )


def test_unsupported_filter_gs501(semantic_env: dict[str, str]) -> None:
    user_id = _create_user(semantic_env)
    _create_org(semantic_env, user_id, f"Org-{user_id}")
    token = _open_session(semantic_env, user_id)
    bad_filter = json.dumps({"any_of": []})
    params = json.dumps({"name": "Org"})
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request("
        f"'{token}', 'core.filter_organizations', '1', '{params}'::jsonb, '{bad_filter}'::jsonb)",
        semantic_env,
        "GS501",
    )


def test_filter_quoting_safe(semantic_env: dict[str, str]) -> None:
    user_id = _create_user(semantic_env)
    org_name = f"Safe'; DROP TABLE portal.\"Organizations\"; -- {uuid.uuid4().hex[:6]}"
    _create_org(semantic_env, user_id, org_name)
    token = _open_session(semantic_env, user_id)
    params = json.dumps({"name": "Safe"})
    rows = _psql(
        "SELECT count(*) FROM portal.sp_run_semantic_request("
        f"'{token}', 'core.filter_organizations', '1', '{params}'::jsonb)",
        semantic_env,
    )
    assert int(rows) == 1
    still = _psql(
        'SELECT count(*) FROM portal."Organizations"',
        semantic_env,
    )
    assert int(still) >= 1


def test_row_cap(semantic_env: dict[str, str]) -> None:
    user_id = _create_user(semantic_env)
    for i in range(5):
        _create_org(semantic_env, user_id, f"CapOrg-{user_id}-{i}")
    token = _open_session(semantic_env, user_id)
    params = json.dumps({"limit": 2})
    rows = _psql(
        "SELECT count(*) FROM portal.sp_run_semantic_request("
        f"'{token}', 'core.list_organizations', '1', '{params}'::jsonb)",
        semantic_env,
    )
    assert int(rows) == 2


def test_permission_denied(semantic_env: dict[str, str]) -> None:
    user_id = _create_user(semantic_env)
    token = _open_session(semantic_env, user_id)
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request("
        f"'{token}', 'core.restricted_probe', '1', '{{}}'::jsonb)",
        semantic_env,
        "GS403",
    )


def test_validate_registry(semantic_env: dict[str, str]) -> None:
    bad = _psql(
        "SELECT count(*) FROM portal.sp_validate_semantic_registry() WHERE ok = false",
        semantic_env,
    )
    assert int(bad) == 0
