"""Generic derivation of action method parameters and owner checks (meta_action_method_derivation.sql)."""

from __future__ import annotations

import json
import uuid

import pytest

from workflow_engine.tests.test_platform_action_methods import _platform_specs, seeded_env  # noqa: F401
from workflow_engine.tests.test_portal_record_editors import _lit, _psql, editor_env  # noqa: F401

INPUT = {
    "title": "TrimTaskInput",
    "type": "object",
    "required": ["sampleName", "inputDir"],
    "properties": {
        "sampleName": {"type": "string", "title": "Sample Name"},
        "inputDir": {"type": "string"},
        "threads": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": 4},
        "tags": {"type": "array", "items": {"type": "string"}, "default": []},
        "mode": {"type": "string", "enum": ["fast", "full"], "default": "fast"},
        "override": {"anyOf": [{"$ref": "#/$defs/StepOverride"}, {"type": "null"}], "default": None},
        "extra": {"anyOf": [{"type": "object"}, {"type": "null"}], "default": None},
    },
    "$defs": {
        "StepOverride": {
            "title": "StepOverride",
            "type": "object",
            "properties": {"tolerance": {"type": "number"}},
        }
    },
}


def _action(env: dict[str, str], name: str, schema: dict | None) -> None:
    _psql(
        f"CALL wf.wf_repo_upsert_semantic_action({_lit(name)}, 'test.cap', 'drv', 'domain', 'rbac', "
        f"{_lit(name)}, '1', NULL, NULL, 'in_process', 'test.handler')",
        env,
    )
    if schema is not None:
        _psql(f"CALL wf.wf_repo_upsert_action_schema({_lit(name)}, 'input', {_lit(json.dumps(schema))}::jsonb)", env)


def _class(env: dict[str, str], name: str, parent: str = "platform/Entity") -> int:
    return int(
        _psql(
            f"""INSERT INTO "Meta"."Classes" ("Name", "ParentID")
                SELECT {_lit(name)}, "ID" FROM "Meta"."Classes" WHERE "Name" = {_lit(parent)} RETURNING "ID" """,
            env,
        )
    )


def _method(env: dict[str, str], class_id: int, name: str, action: str) -> int:
    return int(
        _psql(
            f"""INSERT INTO "Meta"."Methods" ("ClassID", "Name", "ImplKind", "ImplRef")
                VALUES ({class_id}, {_lit(name)}, 'action', {_lit(action)}) RETURNING "ID" """,
            env,
        )
    )


def _derive(env: dict[str, str], ns: str, apply: bool = True) -> dict[str, list[str]]:
    rows = _psql(
        f"""SELECT action_name || '|' || COALESCE(owner_class, '') || '|' || status || '|' || param_count || '|'
                   || COALESCE(semantic_entity, '') || '|' || COALESCE(detail, '')
            FROM "Meta".sp_derive_action_methods({_lit(ns)}, {str(apply).lower()})""",
        env,
    )
    return {r.split("|")[0]: r.split("|")[1:] for r in rows.splitlines() if r}


@pytest.fixture()
def ns(seeded_env: dict[str, str]) -> str:
    return "drv" + uuid.uuid4().hex[:8]


def test_derives_typed_params_binding_and_named_types(seeded_env: dict[str, str], ns: str) -> None:
    env = seeded_env
    cid = _class(env, f"{ns}/Sample")
    action = f"{ns}.sample.trim"
    _action(env, action, INPUT)
    mid = _method(env, cid, "trim", action)
    _psql(
        f"CALL portal.sp_semantic_register_entity({_lit(ns)}, 'sample', 'Sample', '', 's', '1', '', NULL, {cid})", env
    )
    eid = _psql(f"SELECT id FROM portal.semantic_entity WHERE namespace = {_lit(ns)} AND code = 'sample'", env)
    _psql(f"CALL portal.sp_semantic_register_attribute({eid}, 'sample_name', 'sample_name', 'string', 'list', '{{}}')", env)

    dry = _derive(env, ns, apply=False)
    assert dry[action][1:3] == ["derived", "7"]
    assert _psql(f'SELECT count(*) FROM "Meta"."MethodParams" WHERE "MethodID" = {mid}', env) == "0"

    out = _derive(env, ns)
    assert out[action][:4] == [f"{ns}/Sample", "derived", "7", f"{ns}.sample"]
    rows = _psql(
        f"""SELECT p."Name" || ':' || t.name || ':' || p."Required" || ':' || COALESCE(p."DefaultValue"::text, '')
            FROM "Meta"."MethodParams" p JOIN wf.data_type t ON t.id = p."TypeID"
            WHERE p."MethodID" = {mid} ORDER BY p."Ordinal" """,
        env,
    ).splitlines()
    assert rows == [
        "inputDir:platform/action/Text:true:",
        "sampleName:platform/action/Text:true:",
        "extra:platform/action/Document:false:",
        f"mode:{ns}/TrimTaskInput.mode:false:\"fast\"",
        f"override:{ns}/StepOverride:false:",
        "tags:platform/action/TextList:false:[]",
        "threads:platform/action/Integer:false:4",
    ]
    enum_schema = json.loads(_psql(f"SELECT schema_json FROM wf.data_type WHERE name = '{ns}/TrimTaskInput.mode'", env))
    assert enum_schema == {"type": "string", "enum": ["fast", "full"]}
    assert _psql(
        f"""SELECT count(*) FROM portal.semantic_action_binding b JOIN wf.workflow_action a ON a.id = b.workflow_action_id
            WHERE a.action_name = {_lit(action)} AND b.entity_id = {eid}""",
        env,
    ) == "1"
    assert _psql(f"SELECT semantic_entity_id FROM wf.workflow_action WHERE action_name = {_lit(action)}", env) == eid

    again = _derive(env, ns)
    assert again[action][1:3] == ["typed", "7"]


def test_owner_check_flags_missing_and_tolerates_known_duplicates(seeded_env: dict[str, str], ns: str) -> None:
    env = seeded_env
    a_cls = _class(env, f"{ns}/A")
    b_cls = _class(env, f"{ns}/B")
    lot = int(_psql("""SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'platform/Lot'""", env))
    orphan, dup, multi = f"{ns}.orphan", f"{ns}.dup", f"{ns}.multi"
    for name in (orphan, dup, multi):
        _action(env, name, {"type": "object", "properties": {"n": {"type": "integer"}}})
    _method(env, a_cls, "dup", dup)
    _method(env, lot, f"dup_{ns}", dup)
    _method(env, a_cls, "multi", multi)
    _method(env, b_cls, "multi", multi)

    status = dict(
        r.split("|", 1)
        for r in _psql(
            f"""SELECT action_name || '|' || status || ':' || COALESCE(owner_class, '')
                FROM "Meta".fn_check_action_owners() WHERE action_name LIKE {_lit(ns + '.%')}""",
            env,
        ).splitlines()
    )
    assert status == {
        orphan: "no_owner:",
        dup: "known_duplicate:platform/Lot",
        multi: "multiple_owners:",
    }
    for spec in _platform_specs():
        assert _psql(
            f"""SELECT status FROM "Meta".fn_check_action_owners() WHERE action_name = {_lit(spec.action_name)}""", env
        ) == "ok"
    out = _derive(env, ns)
    assert out[multi][1] == "multiple_owners"


def test_conflicting_named_type_is_reported_not_applied(seeded_env: dict[str, str], ns: str) -> None:
    env = seeded_env
    cid = _class(env, f"{ns}/Thing")
    action = f"{ns}.thing.run"
    schema = {"title": "RunInput", "type": "object", "properties": {"mode": {"type": "string", "enum": ["a"]}}}
    _action(env, action, schema)
    mid = _method(env, cid, "run", action)
    _psql(
        f"""INSERT INTO wf.data_type (name, version, status, kind, schema_json, content_hash)
            VALUES ('{ns}/RunInput.mode', '1.0', 'published', 'enum', '{{"type":"string","enum":["b"]}}', 'x')""",
        env,
    )
    out = _derive(env, ns)
    assert out[action][1] == "ambiguous"
    assert "different schema" in out[action][4]
    assert _psql(f'SELECT count(*) FROM "Meta"."MethodParams" WHERE "MethodID" = {mid}', env) == "0"
