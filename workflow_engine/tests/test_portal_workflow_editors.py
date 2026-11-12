"""Workflow graph editor and run inspector (portal_session_workflow_editors_api.sql)."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    if env.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
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


def _lit(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    return "'" + text.replace("'", "''") + "'"


def _make_user(env: dict[str, str], label: str) -> tuple[int, int, int]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('{label}', '{email}', 1) RETURNING "ID" """,
            env,
        )
    )
    org = _psql(f"SELECT * FROM portal.sp_organization_create('{label}Org-{user_id}')", env)
    return user_id, int(org.split("|")[0]), int(org.split("|")[1])


def _author_role(env: dict[str, str], user_id: int, scope_id: int) -> int:
    role_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
                VALUES ('record_editor_{uuid.uuid4().hex[:8]}', false) RETURNING "ID" """,
            env,
        )
    )
    _psql(
        f"""INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
            SELECT {role_id}, p."ID" FROM "RBAC"."Permissions" p
            WHERE p."Name" IN ('platform.model.author', 'meta.schema.read', 'meta.object.read', 'meta.object.write')""",
        env,
    )
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'DIRECT', {scope_id}, true, now() AT TIME ZONE 'utc')""",
        env,
    )
    return role_id


@pytest.fixture(scope="module")
def editor_env() -> dict[str, str]:
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
    return env


@pytest.fixture(scope="module")
def author_token(editor_env: dict[str, str]) -> str:
    from workflow_engine.tests.helpers.portal_session_test_helpers import (
        grant_organization_admin,
        grant_role_nav_tree,
        open_session_token,
    )

    env = editor_env
    psql = lambda sql: _psql(sql, env)  # noqa: E731
    user_id, org_id, scope_id = _make_user(env, "Editor")
    grant_organization_admin(psql, org_id, user_id)
    role_id = _author_role(env, user_id, scope_id)
    grant_role_nav_tree(psql, role_id, scope_id)
    return open_session_token(psql, user_id, scope_id=scope_id, role_id=role_id)


@pytest.fixture(scope="module")
def reader_token(editor_env: dict[str, str]) -> str:
    """Role with every /app nav entitlement but no permissions (no platform.model.author)."""
    from workflow_engine.tests.helpers.portal_session_test_helpers import (
        grant_role_nav_tree,
        open_session_token,
    )

    env = editor_env
    psql = lambda sql: _psql(sql, env)  # noqa: E731
    user_id, _org_id, scope_id = _make_user(env, "Reader")
    role_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
                VALUES ('nav_reader_{uuid.uuid4().hex[:8]}', false) RETURNING "ID" """,
            env,
        )
    )
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'DIRECT', {scope_id}, true, now() AT TIME ZONE 'utc')""",
        env,
    )
    grant_role_nav_tree(psql, role_id, scope_id)
    return open_session_token(psql, user_id, scope_id=scope_id, role_id=role_id)



def _make_workflow(env: dict[str, str]) -> tuple[int, str]:
    suffix = uuid.uuid4().hex[:6]
    action = f"graph_editor_action_{suffix}"
    _psql(f"CALL wf.wf_repo_upsert_workflow_action({_lit(action)}, 'cpu')", env)
    spec = {
        "name": f"graph-editor-{suffix}",
        "root_node_key": "root",
        "nodes": [
            {"node_key": "root", "node_type": "SEQUENCE"},
            {"node_key": "step", "node_type": "ACTION", "action_name": action, "input_template": {"n": 1}},
        ],
        "edges": [{"parent_node_key": "root", "child_node_key": "step", "child_order": 0}],
        "output_bindings": [{"node_key": "step", "var_name": "out", "source_kind": "output"}],
    }
    result = json.loads(_psql(f"SELECT wf.wf_repo_create_workflow_graph({_lit(spec)}::jsonb)", env))
    return int(result["workflow_version_id"]), action


def test_functions_executable_by_portal(editor_env: dict[str, str]) -> None:
    missing = _psql(
        """
        SELECT string_agg(p.oid::regprocedure::text, ', ')
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'portal'
          AND p.proname IN (
            'sp_session_list_graph_versions', 'sp_session_get_workflow_version_spec',
            'sp_session_save_workflow_version', 'sp_session_activate_workflow_version',
            'sp_session_get_run', 'sp_session_cancel_run', 'sp_session_retry_run_node',
            'sp_session_link_run_study')
          AND NOT has_function_privilege('goliath_portal', p.oid, 'EXECUTE')
        """,
        editor_env,
    )
    assert missing == ""


def test_create_graph_still_creates_definition(editor_env: dict[str, str]) -> None:
    version_id, _ = _make_workflow(editor_env)
    row = _psql(
        f"SELECT is_active || '|' || version_major || '.' || version_minor FROM wf.workflow_version WHERE id = {version_id}",
        editor_env,
    )
    assert row == "true|1.0"


def test_save_creates_new_inactive_version(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    base_id, action = _make_workflow(env)
    doc = json.loads(_psql(f"SELECT portal.sp_session_get_workflow_version_spec({_lit(author_token)}, {base_id})", env))
    spec = doc["spec"]
    assert spec["nodes"][1]["input_template"] == {"n": 1}
    nodes = [{k: v for k, v in n.items() if k != "input_template"} for n in spec["nodes"]]
    nodes.append({"node_key": "step2", "node_type": "ACTION", "action_name": action})
    edges = spec["edges"] + [{"parent_node_key": "root", "child_node_key": "step2", "child_order": 1}]
    row = _psql(
        f"""SELECT workflow_version_id || '|' || version_major || '.' || version_minor || '|' || is_active
            FROM portal.sp_session_save_workflow_version({_lit(author_token)}, {base_id},
              {_lit({"nodes": nodes, "edges": edges})}::jsonb)""",
        env,
    )
    new_id, version, active = row.split("|")
    assert version == "1.1"
    assert active == "false"
    new_spec = json.loads(_psql(f"SELECT wf.wf_workflow_version_export_spec({new_id})", env))
    by_key = {n["node_key"]: n for n in new_spec["nodes"]}
    assert by_key["step"]["input_template"] == {"n": 1}
    assert "step2" in by_key
    assert new_spec["output_bindings"] == spec["output_bindings"]
    base_nodes = _psql(f"SELECT count(*) FROM wf.workflow_node WHERE workflow_version_id = {base_id}", env)
    assert base_nodes == "2"
    assert _psql(f"SELECT is_active FROM wf.workflow_version WHERE id = {base_id}", env) == "t"

    _psql(f"SELECT * FROM portal.sp_session_activate_workflow_version({_lit(author_token)}, {new_id})", env)
    assert _psql(f"SELECT is_active FROM wf.workflow_version WHERE id = {new_id}", env) == "t"
    assert _psql(f"SELECT is_active FROM wf.workflow_version WHERE id = {base_id}", env) == "f"
    audit = _psql(
        f"""SELECT string_agg(action_code, ',' ORDER BY audit_id) FROM portal.record_editor_audit
            WHERE entity = 'workflow_version' AND record_key = '{new_id}'""",
        env,
    )
    assert audit == "save_new_version,activate"


def test_graph_writers_require_model_author(editor_env: dict[str, str], reader_token: str) -> None:
    base_id, _ = _make_workflow(editor_env)
    with pytest.raises(RuntimeError, match="model author permission denied"):
        _psql(
            f"SELECT * FROM portal.sp_session_save_workflow_version({_lit(reader_token)}, {base_id}, '{{}}'::jsonb)",
            editor_env,
        )
    with pytest.raises(RuntimeError, match="model author permission denied"):
        _psql(f"SELECT * FROM portal.sp_session_activate_workflow_version({_lit(reader_token)}, {base_id})", editor_env)


def test_invalid_graph_is_rejected(editor_env: dict[str, str], author_token: str) -> None:
    base_id, _ = _make_workflow(editor_env)
    with pytest.raises(RuntimeError, match="invalid workflow graph"):
        _psql(
            f"""SELECT * FROM portal.sp_session_save_workflow_version({_lit(author_token)}, {base_id},
                {_lit({"nodes": [{"node_key": "root", "node_type": "NOPE"}]})}::jsonb)""",
            editor_env,
        )
    with pytest.raises(RuntimeError, match="GS403|permission|denied"):
        _psql(
            f"SELECT * FROM portal.sp_session_save_workflow_version('', {base_id}, '{{}}'::jsonb)",
            editor_env,
        )


def test_run_inspector_and_cancel(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    version_id, _ = _make_workflow(env)
    instance_id = int(
        _psql(
            f"""INSERT INTO wf.workflow_instance (workflow_version_id, status, context_json)
                VALUES ({version_id}, 'RUNNING', '{{}}'::jsonb) RETURNING id""",
            env,
        )
    )
    doc = json.loads(_psql(f"SELECT portal.sp_session_get_run({_lit(author_token)}, {instance_id})", env))
    assert doc["status"] == "RUNNING"
    assert doc["nodes"] == [] and doc["variables"] == [] and doc["study"] is None
    status = _psql(
        f"SELECT status FROM portal.sp_session_cancel_run({_lit(author_token)}, {instance_id}, 'test')", env
    )
    assert status == "CANCELLED"
    _psql(f"UPDATE wf.workflow_instance SET status = 'COMPLETED' WHERE id = {instance_id}", env)
    with pytest.raises(RuntimeError, match="COMPLETED"):
        _psql(f"SELECT * FROM portal.sp_session_cancel_run({_lit(author_token)}, {instance_id}, NULL)", env)
    with pytest.raises(RuntimeError, match="required|not found"):
        _psql(f"SELECT * FROM portal.sp_session_retry_run_node({_lit(author_token)}, -1)", env)
    with pytest.raises(RuntimeError, match="study"):
        _psql(f"SELECT portal.sp_session_link_run_study({_lit(author_token)}, {instance_id}, -1)", env)
