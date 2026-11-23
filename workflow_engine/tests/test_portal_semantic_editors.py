"""Semantic layer record editors (portal_session_semantic_editors_api.sql)."""

from __future__ import annotations

import json
import uuid

import pytest

from workflow_engine.tests.test_portal_record_editors import (  # noqa: F401  (pytest fixtures)
    _lit,
    _psql,
    author_token,
    editor_env,
    reader_token,
)


def _doc(env: dict[str, str], sql: str) -> dict:
    return json.loads(_psql(sql, env))


def test_semantic_editor_functions_executable_by_portal(editor_env: dict[str, str]) -> None:
    missing = _psql(
        """
        SELECT string_agg(p.oid::regprocedure::text, ', ')
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'portal'
          AND p.proname LIKE 'sp\\_session\\_semantic\\_%'
          AND NOT has_function_privilege('goliath_portal', p.oid, 'EXECUTE')
        """,
        editor_env,
    )
    assert missing == ""


def test_platform_namespaces_require_god_architect(editor_env: dict[str, str], author_token: str) -> None:
    with pytest.raises(RuntimeError, match="GS403|god|architect|denied"):
        _psql(
            f"SELECT portal.sp_session_semantic_save_namespace({_lit(author_token)}, 'core', "
            f"{_lit({'display_name': 'Renamed'})}::jsonb)",
            editor_env,
        )


def test_semantic_writers_require_model_author(editor_env: dict[str, str], reader_token: str) -> None:
    with pytest.raises(RuntimeError, match="model author permission denied"):
        _psql(
            f"SELECT portal.sp_session_semantic_save_namespace({_lit(reader_token)}, NULL, "
            f"{_lit({'code': 'denied_ns', 'display_name': 'Denied'})}::jsonb)",
            editor_env,
        )


def test_semantic_namespace_entity_attribute_request_lifecycle(
    editor_env: dict[str, str], author_token: str
) -> None:
    env = editor_env
    tok = _lit(author_token)
    ns = f"ext_{uuid.uuid4().hex[:6]}"

    assert _psql(
        f"SELECT portal.sp_session_semantic_save_namespace({tok}, NULL, "
        f"{_lit({'code': ns, 'display_name': 'Extension', 'owner_app': 'your_app'})}::jsonb)",
        env,
    ) == ns
    assert _doc(env, f"SELECT portal.sp_session_semantic_get_namespace({tok}, {_lit(ns)})")["owner_app"] == "your_app"

    entity_id = int(
        _psql(
            f"SELECT portal.sp_session_semantic_save_entity({tok}, NULL, "
            f"{_lit({'namespace': ns, 'code': 'organization_view', 'display_name': 'Organizations'})}::jsonb)",
            env,
        )
    )
    _psql(
        f"SELECT portal.sp_session_semantic_save_entity({tok}, {entity_id}, "
        f"{_lit({'display_name': 'Orgs', 'description': 'Organization rows'})}::jsonb)",
        env,
    )
    assert _doc(env, f"SELECT portal.sp_session_semantic_get_entity({tok}, {entity_id})")["display_name"] == "Orgs"
    with pytest.raises(RuntimeError, match="does not exist"):
        _psql(
            f"SELECT portal.sp_session_semantic_save_entity({tok}, {entity_id}, "
            f"{_lit({'display_name': 'Orgs', 'storage_relation': 'portal.no_such_relation'})}::jsonb)",
            env,
        )

    attr_id = int(
        _psql(
            f"SELECT portal.sp_session_semantic_save_attribute({tok}, NULL, {_lit({
                'entity_id': entity_id, 'code': 'name', 'column_name': 'name', 'json_type': 'string',
                'role': 'filter', 'filterable_ops': ['eq', 'starts_with'],
            })}::jsonb)",
            env,
        )
    )
    with pytest.raises(RuntimeError, match="operators must be"):
        _psql(
            f"SELECT portal.sp_session_semantic_save_attribute({tok}, {attr_id}, {_lit({
                'column_name': 'name', 'json_type': 'string', 'role': 'filter', 'filterable_ops': ['like'],
            })}::jsonb)",
            env,
        )

    code = f"{ns}.list_orgs"
    params = [
        {"name": "organization_id", "json_type": "integer", "nullable": True},
        {"name": "limit", "json_type": "integer", "nullable": True, "exclusive_minimum": 0, "maximum": 500},
    ]
    base = {
        "request_code": code, "namespace": ns, "entity_id": entity_id, "target_kind": "function",
        "row_type": "core_organization_row", "max_rows": 100, "params": params,
        "required_permission": "meta.object.read",
    }
    # Target must be a real function with the runner signature; no SQL text is accepted.
    for bad in ("portal.no_such_fn", "pg_catalog.pg_sleep", "portal.fn_semantic_core_list_organizations; drop table x"):
        with pytest.raises(RuntimeError, match="target must be"):
            _psql(
                f"SELECT * FROM portal.sp_session_semantic_save_request({tok}, NULL, NULL, "
                f"{_lit({**base, 'target_name': bad})}::jsonb)",
                env,
            )
    with pytest.raises(RuntimeError, match="do not take filters"):
        _psql(
            f"SELECT * FROM portal.sp_session_semantic_save_request({tok}, NULL, NULL, {_lit({
                **base, 'target_name': 'portal.fn_semantic_core_list_organizations',
                'filters': [{'attribute': 'name', 'op': 'eq', 'param': 'organization_id'}],
            })}::jsonb)",
            env,
        )
    saved = _psql(
        f"SELECT request_code || '@' || version FROM portal.sp_session_semantic_save_request({tok}, NULL, NULL, "
        f"{_lit({**base, 'target_name': 'portal.fn_semantic_core_list_organizations'})}::jsonb)",
        env,
    )
    assert saved == f"{code}@1"
    stored = _doc(env, f"SELECT params_schema FROM portal.semantic_request WHERE request_code = {_lit(code)}")
    assert stored["additionalProperties"] is False
    assert stored["properties"]["limit"]["anyOf"][0] == {"type": "integer", "exclusiveMinimum": 0, "maximum": 500}
    result = _doc(env, f"SELECT result_schema FROM portal.semantic_request WHERE request_code = {_lit(code)}")
    assert "name" in result["properties"]

    doc = _doc(env, f"SELECT portal.sp_session_semantic_get_request({tok}, {_lit(code)}, '1')")
    assert doc["params_editable"] is True and doc["status"] == "ACTIVE"
    assert [p["name"] for p in doc["params"]] == ["limit", "organization_id"]

    rows = _psql(f"SELECT count(*) FROM portal.sp_run_semantic_request({tok}, {_lit(code)}, '1', '{{}}'::jsonb)", env)
    assert int(rows) >= 0

    with pytest.raises(RuntimeError, match="retire the request"):
        _psql(f"SELECT portal.sp_session_semantic_delete_request({tok}, {_lit(code)}, '1')", env)
    _psql(f"SELECT portal.sp_session_semantic_set_request_status({tok}, {_lit(code)}, '1', 'RETIRED')", env)
    with pytest.raises(RuntimeError, match="retired"):
        _psql(f"SELECT count(*) FROM portal.sp_run_semantic_request({tok}, {_lit(code)}, '1', '{{}}'::jsonb)", env)
    assert _psql(
        f"SELECT count(*) FROM portal.sp_list_semantic_catalog({tok}) WHERE request_code = {_lit(code)}", env
    ) == "0"

    # Entity and namespace cannot be deleted while a request uses them.
    with pytest.raises(RuntimeError, match="still has requests"):
        _psql(f"SELECT portal.sp_session_semantic_delete_entity({tok}, {entity_id})", env)
    assert _psql(f"SELECT portal.sp_session_semantic_delete_request({tok}, {_lit(code)}, '1')", env) == "deleted"
    with pytest.raises(RuntimeError, match="entities or requests"):
        _psql(f"SELECT portal.sp_session_semantic_delete_namespace({tok}, {_lit(ns)})", env)
    assert _psql(f"SELECT portal.sp_session_semantic_delete_attribute({tok}, {attr_id})", env) == "deleted"
    assert _psql(f"SELECT portal.sp_session_semantic_delete_entity({tok}, {entity_id})", env) == "deleted"
    assert _psql(f"SELECT portal.sp_session_semantic_delete_namespace({tok}, {_lit(ns)})", env) == "deleted"
    audit = _psql(
        "SELECT string_agg(DISTINCT entity, ',' ORDER BY entity) FROM portal.record_editor_audit "
        f"WHERE entity LIKE 'semantic%' AND record_key IN ({_lit(ns)}, {_lit(str(entity_id))}, {_lit(str(attr_id))}, {_lit(code + '@1')})",
        env,
    )
    assert audit == "semantic_attribute,semantic_entity,semantic_namespace,semantic_request"


def test_pydantic_params_schema_round_trips(editor_env: dict[str, str]) -> None:
    schema = {
        "additionalProperties": False,
        "properties": {
            "limit": {
                "anyOf": [{"exclusiveMinimum": 0, "maximum": 500, "type": "integer"}, {"type": "null"}],
                "default": None,
                "title": "Limit",
            },
            "organization_id": {"title": "Organization Id", "type": "integer"},
            "item_id": {"title": "Item Id", "type": "integer"},
        },
        "required": ["organization_id", "item_id"],
        "title": "StockLotsByItemParams",
        "type": "object",
    }
    assert _psql(f"SELECT portal.fn_semantic_params_editable({_lit(schema)}::jsonb)", editor_env) == "t"
    odd = {**schema, "properties": {**schema["properties"], "mode": {"type": "string", "enum": ["a", "b"]}}}
    assert _psql(f"SELECT portal.fn_semantic_params_editable({_lit(odd)}::jsonb)", editor_env) == "f"


@pytest.mark.parametrize(
    "kind",
    [
        "semantic_namespace",
        "semantic_entity",
        "semantic_attribute",
        "semantic_row_type",
        "semantic_target_function",
        "semantic_template_target",
        "permission",
    ],
)
def test_semantic_reference_kinds(editor_env: dict[str, str], author_token: str, kind: str) -> None:
    _psql(
        f"SELECT count(*) FROM portal.sp_session_search_references({_lit(author_token)}, {_lit(kind)}, '', 20)",
        editor_env,
    )


def test_target_function_picker_lists_runner_signature_only(editor_env: dict[str, str], author_token: str) -> None:
    values = _psql(
        f"SELECT string_agg(ref_value, ',') FROM portal.sp_session_search_references("
        f"{_lit(author_token)}, 'semantic_target_function', 'organizations', 50)",
        editor_env,
    ).split(",")
    assert "portal.fn_semantic_core_list_organizations" in values
    assert "portal.fn_semantic_core_filter_organizations" in values  # template target
