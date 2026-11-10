"""Integration tests for semantic layer runner (A2)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from workflow_engine.tests.helpers.portal_session_test_helpers import (
    create_org_with_admin,
    open_session_token,
)

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
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath"))
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
            "\\set VERBOSITY sqlstate",
            "-c",
            sql,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0, "expected failure"
    combined = (proc.stderr or "") + (proc.stdout or "")
    match = re.search(r"\b(GS\d{3})\b", combined)
    assert match is not None, f"expected semantic SQLSTATE in: {combined!r}"
    assert match.group(1) == errcode, (
        f"expected SQLSTATE {errcode}, got {match.group(1)!r} in: {combined!r}"
    )
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


def _open_session(env: dict[str, str], user_id: int, scope_id: int | None = None) -> str:
    return open_session_token(lambda sql: _psql(sql, env), user_id, scope_id=scope_id)


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


def _create_org(env: dict[str, str], user_id: int, name: str) -> tuple[int, int]:
    return create_org_with_admin(lambda sql: _psql(sql, env), user_id, name)


def test_session_denied(semantic_env: dict[str, str]) -> None:
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request('not-a-token', 'core.list_organizations')",
        semantic_env,
        "GS401",
    )


def test_cross_organization_denied(semantic_env: dict[str, str]) -> None:
    user_a = _create_user(semantic_env)
    user_b = _create_user(semantic_env)
    org_b, _scope_b = _create_org(semantic_env, user_b, f"OrgB-{user_b}")
    _org_a, scope_a = _create_org(semantic_env, user_a, f"OrgA-{user_a}")
    token_a = _open_session(semantic_env, user_a, scope_id=scope_a)
    params = json.dumps({"organization_id": org_b})
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request("
        f"'{token_a}', 'core.list_organizations', '1', '{params}'::jsonb)",
        semantic_env,
        "GS403",
    )


def test_invalid_limit_param_gs400(semantic_env: dict[str, str]) -> None:
    user_id = _create_user(semantic_env)
    _org_id, scope_id = _create_org(semantic_env, user_id, f"Org-{user_id}")
    token = _open_session(semantic_env, user_id, scope_id=scope_id)
    params = json.dumps({"limit": "not-an-integer"})
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request("
        f"'{token}', 'core.list_organizations', '1', '{params}'::jsonb)",
        semantic_env,
        "GS400",
    )


def test_missing_param_gs400(semantic_env: dict[str, str]) -> None:
    user_id = _create_user(semantic_env)
    _org_id, scope_id = _create_org(semantic_env, user_id, f"Org-{user_id}")
    token = _open_session(semantic_env, user_id, scope_id=scope_id)
    _psql_expect_error(
        "SELECT * FROM portal.sp_run_semantic_request("
        f"'{token}', 'core.filter_organizations', '1', '{{}}'::jsonb)",
        semantic_env,
        "GS400",
    )


def test_unsupported_filter_gs501(semantic_env: dict[str, str]) -> None:
    user_id = _create_user(semantic_env)
    _org_id, scope_id = _create_org(semantic_env, user_id, f"Org-{user_id}")
    token = _open_session(semantic_env, user_id, scope_id=scope_id)
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
    _org_id, scope_id = _create_org(semantic_env, user_id, org_name)
    token = _open_session(semantic_env, user_id, scope_id=scope_id)
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
    scope_id = None
    for i in range(5):
        _org_id, scope_id = _create_org(semantic_env, user_id, f"CapOrg-{user_id}-{i}")
    assert scope_id is not None
    token = _open_session(semantic_env, user_id, scope_id=scope_id)
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


def test_portal_role_cannot_execute_filter_internals(semantic_env: dict[str, str]) -> None:
    _psql(
        """
        DO $do$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'goliath_portal') THEN
            RAISE EXCEPTION 'goliath_portal role missing';
          END IF;
          BEGIN
            EXECUTE 'SET LOCAL ROLE goliath_portal';
            PERFORM portal.fn_semantic_core_filter_organizations(
              1, '{}'::jsonb, 10, 1, '{"all_of": []}'::jsonb
            );
            RAISE EXCEPTION 'filter executor should not be callable as goliath_portal';
          EXCEPTION
            WHEN insufficient_privilege THEN
              NULL;
          END;
        END $do$;
        """,
        semantic_env,
    )


def test_validate_registry(semantic_env: dict[str, str]) -> None:
    bad = _psql(
        "SELECT count(*) FROM portal.sp_validate_semantic_registry() WHERE ok = false",
        semantic_env,
    )
    assert int(bad) == 0
