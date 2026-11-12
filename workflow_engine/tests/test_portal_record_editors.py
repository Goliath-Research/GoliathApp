"""Workflows record editors (portal_session_record_editors_api.sql)."""

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


def _class(env: dict[str, str], token: str, name: str, parent: str) -> None:
    _psql(
        f"SELECT class_id FROM portal.sp_session_meta_class_create({_lit(token)}, {_lit(name)}, {_lit(parent)})",
        env,
    )


def _any_data_type(env: dict[str, str]) -> int:
    value = _psql(
        "SELECT id FROM wf.data_type WHERE class_id IS NULL AND status IS DISTINCT FROM 'retired' ORDER BY id LIMIT 1",
        env,
    )
    if not value:
        pytest.skip("no data types available")
    return int(value)


def test_functions_executable_by_portal(editor_env: dict[str, str]) -> None:
    missing = _psql(
        """
        SELECT string_agg(p.oid::regprocedure::text, ', ')
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'portal'
          AND p.proname IN (
            'sp_session_list_class_methods', 'sp_session_get_class_method', 'sp_session_save_class_method',
            'sp_session_save_method_param_defaults', 'sp_session_get_domain_program',
            'sp_session_save_domain_program', 'sp_session_publish_domain_program', 'sp_session_list_clusters',
            'sp_session_get_cluster', 'sp_session_save_cluster', 'sp_session_save_worker_enrollment',
            'sp_session_revoke_worker_enrollment', 'sp_session_get_event_subscription',
            'sp_session_save_event_subscription')
          AND NOT has_function_privilege('goliath_portal', p.oid, 'EXECUTE')
        """,
        editor_env,
    )
    assert missing == ""


def test_writers_require_model_author(editor_env: dict[str, str], reader_token: str) -> None:
    with pytest.raises(RuntimeError, match="model author permission denied"):
        _psql(
            f"SELECT portal.sp_session_save_cluster({_lit(reader_token)}, {_lit({'cluster_key': 'denied'})}::jsonb)",
            editor_env,
        )


def test_anonymous_session_denied(editor_env: dict[str, str]) -> None:
    with pytest.raises(RuntimeError, match="session"):
        _psql("SELECT * FROM portal.sp_session_list_class_methods('')", editor_env)


def test_method_save_syncs_action_catalog_and_inheritance(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    suffix = uuid.uuid4().hex[:6]
    base, child = f"your_app/EditorBase_{suffix}", f"your_app/EditorChild_{suffix}"
    _class(env, author_token, base, "platform/Entity")
    _class(env, author_token, child, base)
    type_id = _any_data_type(env)
    action_name = f"editor_test_action_{suffix}"

    method_id = int(
        _psql(
            f"""SELECT portal.sp_session_save_class_method({_lit(author_token)}, NULL, {_lit({
                "class_name": base,
                "method_name": "run",
                "impl_kind": "action",
                "impl_ref": action_name,
                "parameters": [{"name": "count", "type_id": type_id, "required": True}],
                "action": {"capability": "cpu", "execution_mode": "in_process"},
            })}::jsonb)""",
            env,
        )
    )
    action = _psql(
        f"""SELECT capability || '|' || execution_mode || '|' || (input_type_id IS NOT NULL)
            FROM wf.workflow_action WHERE action_name = {_lit(action_name)}""",
        env,
    )
    assert action == "cpu|in_process|true"

    rows = _psql(
        f"""SELECT class_name || ':' || inherited || ':' || declared_on_class
            FROM portal.sp_session_list_class_methods({_lit(author_token)})
            WHERE method_id = {method_id} ORDER BY class_name""",
        env,
    ).splitlines()
    assert f"{base}:false:{base}" in rows
    assert f"{child}:true:{base}" in rows

    doc = json.loads(
        _psql(f"SELECT portal.sp_session_get_class_method({_lit(author_token)}, {method_id})", env)
    )
    assert doc["action_name"] == action_name
    assert doc["parameters"][0]["name"] == "count"
    assert doc["parameters"][0]["required"] is True
    assert "count" in doc["defaults_schema"]["properties"]

    override_id = int(
        _psql(
            f"""SELECT portal.sp_session_save_class_method({_lit(author_token)}, NULL, {_lit({
                "class_name": child,
                "method_name": "run",
                "impl_kind": "action",
                "action_name": action_name,
            })}::jsonb)""",
            env,
        )
    )
    assert (
        _psql(f"""SELECT "IsOverride" FROM "Meta"."Methods" WHERE "ID" = {override_id}""", env) == "t"
    )
    inherited = _psql(
        f"""SELECT count(*) FROM portal.sp_session_list_class_methods({_lit(author_token)})
            WHERE class_name = {_lit(child)} AND method_name = 'run' AND inherited""",
        env,
    )
    assert inherited == "0"

    with pytest.raises(RuntimeError, match="unknown parameter"):
        _psql(
            f"SELECT portal.sp_session_save_method_param_defaults({_lit(author_token)}, {method_id}, "
            f"{_lit({'nope': 1})}::jsonb)",
            env,
        )

    audit = _psql(
        f"""SELECT count(*) FROM portal.record_editor_audit
            WHERE entity = 'class_method' AND record_key IN ('{method_id}', '{override_id}')""",
        env,
    )
    assert int(audit) >= 2


def test_final_methods_cannot_be_overridden(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    suffix = uuid.uuid4().hex[:6]
    base, child = f"your_app/FinalBase_{suffix}", f"your_app/FinalChild_{suffix}"
    _class(env, author_token, base, "platform/Entity")
    _class(env, author_token, child, base)
    _psql(
        f"""SELECT portal.sp_session_save_class_method({_lit(author_token)}, NULL, {_lit({
            "class_name": base, "method_name": "locked", "impl_kind": "abstract", "is_final": True,
        })}::jsonb)""",
        env,
    )
    with pytest.raises(RuntimeError, match="final"):
        _psql(
            f"""SELECT portal.sp_session_save_class_method({_lit(author_token)}, NULL, {_lit({
                "class_name": child, "method_name": "locked", "impl_kind": "abstract",
            })}::jsonb)""",
            env,
        )


def test_domain_program_metadata_preserves_body(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    name = f"editor-program-{uuid.uuid4().hex[:6]}"
    _psql(
        f"""SELECT * FROM portal.sp_session_save_domain_program({_lit(author_token)}, {_lit({
            "name": name, "version": "1", "description": "first",
        })}::jsonb)""",
        env,
    )
    _psql(
        f"""UPDATE cfg.domain_program SET document_json = document_json || '{{"body": [{{"kind": "x"}}]}}'::jsonb
            WHERE name = {_lit(name)} AND version = '1'""",
        env,
    )
    _psql(
        f"""SELECT * FROM portal.sp_session_save_domain_program({_lit(author_token)}, {_lit({
            "name": name, "version": "1", "description": "second",
        })}::jsonb)""",
        env,
    )
    stored = json.loads(
        _psql(f"SELECT document_json FROM cfg.domain_program WHERE name = {_lit(name)} AND version = '1'", env)
    )
    assert stored["description"] == "second"
    assert stored["body"] == [{"kind": "x"}]
    _psql(
        f"""SELECT * FROM portal.sp_session_save_domain_program({_lit(author_token)}, {_lit({
            "name": name, "version": "1", "description": "",
        })}::jsonb)""",
        env,
    )
    cleared = json.loads(
        _psql(f"SELECT document_json FROM cfg.domain_program WHERE name = {_lit(name)} AND version = '1'", env)
    )
    assert "description" not in cleared

    _psql(f"UPDATE cfg.domain_program SET status = 'published' WHERE name = {_lit(name)}", env)
    with pytest.raises(RuntimeError, match="immutable"):
        _psql(
            f"""SELECT * FROM portal.sp_session_save_domain_program({_lit(author_token)}, {_lit({
                "name": name, "version": "1", "description": "third",
            })}::jsonb)""",
            env,
        )
    _psql(
        f"""SELECT * FROM portal.sp_session_save_domain_program({_lit(author_token)}, {_lit({
            "name": name, "version": "2",
        })}::jsonb)""",
        env,
    )
    v2 = json.loads(
        _psql(f"SELECT document_json FROM cfg.domain_program WHERE name = {_lit(name)} AND version = '2'", env)
    )
    assert v2["body"] == [{"kind": "x"}]


def test_cluster_and_enrollment_round_trip(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    key = f"editor-cluster-{uuid.uuid4().hex[:6]}"
    _psql(
        f"""SELECT portal.sp_session_save_cluster({_lit(author_token)}, {_lit({
            "cluster_key": key, "name": "Editor cluster", "allowed_source_cidrs": ["10.0.0.0/8"],
        })}::jsonb)""",
        env,
    )
    doc = json.loads(_psql(f"SELECT portal.sp_session_get_cluster({_lit(author_token)}, {_lit(key)})", env))
    assert doc["name"] == "Editor cluster"
    assert doc["allowed_source_cidrs"] == ["10.0.0.0/8"]
    with pytest.raises(RuntimeError, match="status"):
        _psql(
            f"""SELECT portal.sp_session_save_cluster({_lit(author_token)}, {_lit({
                "cluster_key": key, "status": "RUNNING",
            })}::jsonb)""",
            env,
        )
    _psql(
        f"""SELECT portal.sp_session_save_worker_enrollment({_lit(author_token)}, {_lit({
            "cluster_key": key, "public_ip": "192.0.2.10", "external_worker_key": "w1",
        })}::jsonb)""",
        env,
    )
    status = _psql(
        f"SELECT portal.sp_session_revoke_worker_enrollment({_lit(author_token)}, {_lit(key)}, 'w1')", env
    )
    assert status == "REVOKED"


def test_event_subscription_create_and_edit(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    version_id = _psql("SELECT id FROM wf.workflow_version ORDER BY id LIMIT 1", env)
    if not version_id:
        pytest.skip("no workflow versions available")
    event_type = f"editor.test.{uuid.uuid4().hex[:6]}"
    _psql(f"INSERT INTO wf.event_type (name) VALUES ({_lit(event_type)})", env)
    sub_id = int(
        _psql(
            f"""SELECT portal.sp_session_save_event_subscription({_lit(author_token)}, NULL, {_lit({
                "event_type": event_type,
                "workflow_version_id": int(version_id),
                "mode": "start_instance",
                "filter": [{"key": "site", "value": "a"}, {"key": "n", "value": "2", "value_type": "number"}],
            })}::jsonb)""",
            env,
        )
    )
    stored = json.loads(_psql(f"SELECT filter_json FROM wf.event_subscription WHERE id = {sub_id}", env))
    assert stored == {"site": "a", "n": 2}
    assert _psql(f"SELECT enabled FROM wf.event_subscription WHERE id = {sub_id}", env) == "f"
    _psql(
        f"""SELECT portal.sp_session_save_event_subscription({_lit(author_token)}, {sub_id}, {_lit({
            "event_type": event_type, "workflow_version_id": int(version_id), "mode": "signal_wait",
            "enabled": False,
        })}::jsonb)""",
        env,
    )
    doc = json.loads(
        _psql(f"SELECT portal.sp_session_get_event_subscription({_lit(author_token)}, {sub_id})", env)
    )
    assert doc["mode"] == "signal_wait"
    assert doc["enabled"] is False
    with pytest.raises(RuntimeError, match="event_type"):
        _psql(
            f"""SELECT portal.sp_session_save_event_subscription({_lit(author_token)}, NULL, {_lit({
                "event_type": "does.not.exist", "workflow_version_id": int(version_id), "mode": "start_instance",
            })}::jsonb)""",
            env,
        )


def test_platform_class_methods_require_god_architect(editor_env: dict[str, str], author_token: str) -> None:
    with pytest.raises(RuntimeError, match="GS403|god|architect|denied"):
        _psql(
            f"""SELECT portal.sp_session_save_class_method({_lit(author_token)}, NULL, {_lit({
                "class_name": "platform/Entity", "method_name": f"blocked_{uuid.uuid4().hex[:6]}",
                "impl_kind": "abstract",
            })}::jsonb)""",
            editor_env,
        )
