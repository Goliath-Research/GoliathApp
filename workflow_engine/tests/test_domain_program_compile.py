"""Domain program step edits and server-side compile/publish (portal_session_domain_program_compile_api.sql)."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

from workflow_engine.tests.test_platform_action_methods import _platform_specs, seeded_env  # noqa: F401
from workflow_engine.tests.test_portal_record_editors import (  # noqa: F401  (pytest fixtures)
    _lit,
    _psql,
    author_token,
    editor_env,
    reader_token,
)

SQL = Path(__file__).resolve().parents[1] / "sql_pg" / "portal_session_domain_program_compile_api.sql"


def _compile_service():
    from domain import compile_service

    return compile_service


def test_platform_profile_seed_matches_catalog() -> None:
    text = SQL.read_text(encoding="utf-8")
    block = text[text.index("FROM (VALUES") : text.index(") AS v(action_name, tool)")]
    seeded = dict(re.findall(r"\('([a-z_.]+)', '([a-z_.-]+)'\)", block))
    expected = {s.action_name: (s.tool or s.action_name) for s in _platform_specs()}
    assert seeded == expected
    for spec in _platform_specs():
        assert spec.action_config_key is None and not spec.context_vars and spec.domain_effects is None


def test_service_uses_given_catalog() -> None:
    svc = _compile_service()
    program = {
        "name": "svc-test",
        "projectPath": "/p",
        "body": [{"do": "app.thing", "with": {"n": 2}}],
    }
    out = svc.compile_payload(
        {"program": program, "actions": [{"action_name": "app.thing", "tool": "app-tool", "context_vars": ["runId"]}]}
    )
    node = next(n for n in out["spec"]["nodes"] if n["node_type"] == "ACTION")
    assert node["action_name"] == "app.thing"
    assert node["input_template"]["tool"] == "app-tool"
    assert node["input_template"]["runId"] == "${var.runId}"
    assert node["input_template"]["n"] == 2
    with pytest.raises(ValueError, match="unknown action"):
        svc.compile_payload({"program": program, "actions": []})


def test_service_domain_effects_round_trip() -> None:
    from dataclasses import asdict

    from goliath_app.actions.domain_effects import DomainEffects, OutputBindingRule, TemplateDefaultRule

    svc = _compile_service()
    effects = DomainEffects(
        scope_bindings=(("lotId", "$.lot_id"),),
        output_bindings=(OutputBindingRule(scope_field="qty", output_json_path="$.qty"),),
        template_defaults=(TemplateDefaultRule(field="site", scope_var="siteId"),),
    )
    parsed = svc._effects(json.loads(json.dumps(asdict(effects))))
    assert parsed == effects


def _profiles(env: dict[str, str]) -> None:
    from workflow_engine.sql_pg.seed_action_catalog import compile_profile_args

    for spec in _platform_specs():
        a = compile_profile_args(spec)
        _psql(
            f"SELECT wf.wf_repo_upsert_action_compile_profile({_lit(a[0])}, {_lit(a[1])}, NULL, '{{}}', NULL)",
            env,
        )


def _draft(env: dict[str, str], body: list, variables: dict | None = None) -> str:
    name = f"compile-prog-{uuid.uuid4().hex[:6]}"
    doc = {"name": name, "projectPath": "/proj", "variables": variables or {}, "body": body}
    _psql(f"SELECT * FROM portal.sp_upsert_domain_program({_lit(name)}, '1', 'draft', {_lit(doc)}::jsonb)", env)
    return name


def test_functions_executable_by_portal(editor_env: dict[str, str]) -> None:
    missing = _psql(
        """
        SELECT string_agg(p.oid::regprocedure::text, ', ')
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'portal'
          AND p.proname IN (
            'sp_session_domain_program_step_list', 'sp_session_domain_program_step_get',
            'sp_session_domain_program_step_save', 'sp_session_domain_program_compile_input',
            'sp_session_domain_program_publish_compiled')
          AND NOT has_function_privilege('goliath_portal', p.oid, 'EXECUTE')
        """,
        editor_env,
    )
    assert missing == ""
    assert (
        _psql(
            "SELECT has_function_privilege('goliath_portal', "
            "'wf.wf_repo_upsert_action_compile_profile(text,text,text,text[],jsonb)', 'EXECUTE')",
            editor_env,
        )
        == "f"
    )


def test_step_edit_compile_publish(seeded_env: dict[str, str], author_token: str) -> None:  # noqa: F811
    env = seeded_env
    _profiles(env)
    name = _draft(
        env,
        [
            {"do": "workflow.const_int", "with": {"value": 1}},
            {"if": "${var.flag}", "then": [{"assign": "n", "using": "workflow.const_int", "with": {"value": "${var.m}"}}]},
        ],
        {"n": {"schemaRef": "schemas/vars/int.schema.json"}},
    )
    steps = _psql(
        f"""SELECT step_path || '|' || action_name || '|' || editable
            FROM portal.sp_session_domain_program_step_list({_lit(author_token)}) WHERE program = {_lit(name)}""",
        env,
    ).splitlines()
    assert steps == ["body.0|workflow.const_int|true", "body.1.then.0|workflow.const_int|true"]

    got = json.loads(
        _psql(f"SELECT portal.sp_session_domain_program_step_get({_lit(author_token)}, {_lit(name + '@1#body.1.then.0')})", env)
    )
    assert got["document"] == {"value": "${var.m}"}
    assert got["document_schema"]["properties"]["value"]["type"] == "string"

    key = f"{name}@1#body.0"
    with pytest.raises(RuntimeError, match="GS400"):
        _psql(f"SELECT portal.sp_session_domain_program_step_save({_lit(author_token)}, {_lit(key)}, {_lit({'document': {'value': 'x'}})}::jsonb)", env)
    with pytest.raises(RuntimeError, match="GS400"):
        _psql(f"SELECT portal.sp_session_domain_program_step_save({_lit(author_token)}, {_lit(key)}, {_lit({'document': {'other': 1}})}::jsonb)", env)
    _psql(f"SELECT portal.sp_session_domain_program_step_save({_lit(author_token)}, {_lit(key)}, {_lit({'document': {'value': 7}})}::jsonb)", env)
    body = json.loads(_psql(f"SELECT document_json->'body' FROM cfg.domain_program WHERE name = {_lit(name)}", env))
    assert body[0]["with"] == {"value": 7}

    payload = json.loads(
        _psql(f"SELECT portal.sp_session_domain_program_compile_input({_lit(author_token)}, {_lit(name)}, '1')", env)
    )
    assert [a["action_name"] for a in payload["actions"]] == ["workflow.const_int"]
    out = _compile_service().compile_payload(payload)
    assert out["ok"]
    res = json.loads(
        _psql(
            f"SELECT portal.sp_session_domain_program_publish_compiled({_lit(author_token)}, {_lit(name)}, '1', {_lit(out['spec'])}::jsonb)",
            env,
        )
    )
    wv = res["workflow_version_id"]
    assert _psql(f"SELECT is_active FROM wf.workflow_version WHERE id = {wv}", env) == "f"
    assert _psql(
        f"SELECT status || '|' || compiled_workflow_version_id FROM cfg.domain_program WHERE name = {_lit(name)}", env
    ) == f"published|{wv}"
    with pytest.raises(RuntimeError, match="GS409"):
        _psql(f"SELECT portal.sp_session_domain_program_step_save({_lit(author_token)}, {_lit(key)}, {_lit({'document': {'value': 8}})}::jsonb)", env)
    with pytest.raises(RuntimeError, match="GS409"):
        _psql(f"SELECT portal.sp_session_domain_program_compile_input({_lit(author_token)}, {_lit(name)}, '1')", env)


def test_missing_profile_and_untyped_steps(seeded_env: dict[str, str], author_token: str) -> None:  # noqa: F811
    env = seeded_env
    action = f"app.untyped_{uuid.uuid4().hex[:6]}"
    _psql(f"CALL wf.wf_repo_upsert_workflow_action({_lit(action)}, 'cpu')", env)
    name = _draft(env, [{"do": action, "with": {"a": 1}}])
    key = f"{name}@1#body.0"
    got = json.loads(_psql(f"SELECT portal.sp_session_domain_program_step_get({_lit(author_token)}, {_lit(key)})", env))
    assert got["document_schema"] is None
    with pytest.raises(RuntimeError, match="GS409"):
        _psql(f"SELECT portal.sp_session_domain_program_step_save({_lit(author_token)}, {_lit(key)}, {_lit({'document': {'a': 2}})}::jsonb)", env)
    with pytest.raises(RuntimeError, match="no compile profile"):
        _psql(f"SELECT portal.sp_session_domain_program_compile_input({_lit(author_token)}, {_lit(name)}, '1')", env)


def test_publish_rejects_foreign_graph(seeded_env: dict[str, str], author_token: str) -> None:  # noqa: F811
    env = seeded_env
    name = _draft(env, [{"do": "workflow.const_int", "with": {"value": 1}}])
    spec = {"name": "other", "root_node_key": "root", "nodes": [{"node_key": "root", "node_type": "SEQUENCE"}], "edges": []}
    with pytest.raises(RuntimeError, match="GS400"):
        _psql(f"SELECT portal.sp_session_domain_program_publish_compiled({_lit(author_token)}, {_lit(name)}, '1', {_lit(spec)}::jsonb)", env)
    spec["name"] = name
    spec["nodes"].append({"node_key": "x", "node_type": "ACTION", "action_name": "nope.missing"})
    with pytest.raises(RuntimeError, match="unknown actions"):
        _psql(f"SELECT portal.sp_session_domain_program_publish_compiled({_lit(author_token)}, {_lit(name)}, '1', {_lit(spec)}::jsonb)", env)


def test_step_writes_need_model_author(seeded_env: dict[str, str], reader_token: str) -> None:  # noqa: F811
    env = seeded_env
    name = _draft(env, [{"do": "workflow.const_int", "with": {"value": 1}}])
    with pytest.raises(RuntimeError, match="GS403|denied|author"):
        _psql(
            f"SELECT portal.sp_session_domain_program_step_save({_lit(reader_token)}, {_lit(name + '@1#body.0')}, {_lit({'document': {'value': 2}})}::jsonb)",
            env,
        )
