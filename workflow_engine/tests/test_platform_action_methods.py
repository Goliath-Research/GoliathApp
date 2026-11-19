"""Platform actions as Meta class methods (platform_action_methods_seed.sql)."""

from __future__ import annotations

import pytest

from workflow_engine.tests.test_portal_record_editors import (  # noqa: F401  (pytest fixtures)
    _lit,
    _psql,
    editor_env,
)

EXPECTED = {
    "workflow.const_bool": ("platform/Workflow", "const_bool", ["value"]),
    "workflow.const_int": ("platform/Workflow", "const_int", ["value"]),
    "workflow.const_string": ("platform/Workflow", "const_string", ["value"]),
    "workflow.const_path": ("platform/Workflow", "const_path", ["value"]),
    "workflow.json_path_bool": ("platform/Workflow", "json_path_bool", ["document", "jsonPath"]),
    "workflow.json_path_int": ("platform/Workflow", "json_path_int", ["document", "jsonPath"]),
    "workflow.json_path_string": ("platform/Workflow", "json_path_string", ["document", "jsonPath"]),
    "workflow.fs_stat": ("platform/Workflow", "fs_stat", ["path", "check"]),
    "workflow.device_adapter.command": (
        "platform/Workflow",
        "device_adapter_command",
        ["command_key", "arguments", "idempotency_key", "correlation_key", "timeout_seconds", "target"],
    ),
    "workflow.device_adapter.observe": ("platform/Workflow", "device_adapter_observe", ["observe_key", "context"]),
    "validation.plan_iterations": (
        "platform/Activity",
        "plan_iterations",
        [
            "projectPath",
            "featureIterations",
            "qualityIterations",
            "seed",
            "trainFraction",
            "layout",
            "iterations",
        ],
    ),
    "inv.stock.receive": (
        "platform/Lot",
        "receive_stock",
        ["organization_id", "user_id", "po_line_id", "bin_id", "qty", "lot_number", "unit_price_override"],
    ),
    "inv.stock.adjust": (
        "platform/Lot",
        "adjust_stock",
        ["organization_id", "user_id", "stock_lot_id", "qty_delta", "reason_code"],
    ),
    "inv.stock.issue": (
        "platform/Lot",
        "issue_stock",
        ["organization_id", "user_id", "stock_lot_id", "qty", "ref_type", "ref_id"],
    ),
}


def _platform_specs():
    from goliath_app.core.catalog import ACTION_CATALOG as core
    from goliath_app.engine.catalog import ACTION_CATALOG as engine
    from goliath_app.inv.catalog import ACTION_CATALOG as inv

    return [*engine, *core, *inv]


@pytest.fixture(scope="module")
def seeded_env(editor_env: dict[str, str]) -> dict[str, str]:
    for spec in _platform_specs():
        _psql(
            "CALL wf.wf_repo_upsert_semantic_action("
            f"{_lit(spec.action_name)}, {_lit(spec.resolved_capability)}, {_lit(spec.namespace)}, "
            f"{_lit(spec.level.value)}, {_lit(spec.resolved_exposure.value)}, {_lit(spec.display_name)}, "
            f"{_lit(spec.schema_version)}, NULL, NULL, 'in_process', {_lit(spec.in_process_handler)})",
            editor_env,
        )
    _psql('SELECT "Meta".sp_seed_platform_action_methods()', editor_env)
    return editor_env


def test_every_platform_action_is_a_class_method(seeded_env: dict[str, str]) -> None:
    names = {spec.action_name for spec in _platform_specs()}
    assert names == set(EXPECTED), "update EXPECTED and the seed when platform actions change"
    for action, (cls, method, params) in EXPECTED.items():
        row = _psql(
            f"""SELECT m."ImplKind" || '|' || m."ImplRef"
                FROM "Meta"."Methods" m JOIN "Meta"."Classes" c ON c."ID" = m."ClassID"
                WHERE c."Name" = {_lit(cls)} AND m."Name" = {_lit(method)}""",
            seeded_env,
        )
        assert row == f"action|{action}"
        got = _psql(
            f"""SELECT string_agg(p."Name", ',' ORDER BY p."Ordinal")
                FROM "Meta"."MethodParams" p
                JOIN "Meta"."Methods" m ON m."ID" = p."MethodID"
                JOIN "Meta"."Classes" c ON c."ID" = m."ClassID"
                WHERE c."Name" = {_lit(cls)} AND m."Name" = {_lit(method)}""",
            seeded_env,
        )
        assert got.split(",") == params


def test_parameters_are_typed_by_catalog_types(seeded_env: dict[str, str]) -> None:
    untyped = _psql(
        """SELECT count(*) FROM "Meta"."MethodParams" p
           JOIN "Meta"."Methods" m ON m."ID" = p."MethodID"
           JOIN "Meta"."Classes" c ON c."ID" = m."ClassID"
           LEFT JOIN wf.data_type t ON t.id = p."TypeID"
           WHERE c."Name" IN ('platform/Workflow', 'platform/Activity', 'platform/Lot')
             AND m."ImplKind" = 'action'
             AND (t.name IS NULL OR t.name NOT LIKE 'platform/action/%')""",
        seeded_env,
    )
    assert untyped == "0"
    default = _psql(
        """SELECT p."DefaultValue"::text FROM "Meta"."MethodParams" p
           JOIN "Meta"."Methods" m ON m."ID" = p."MethodID"
           WHERE m."ImplRef" = 'workflow.fs_stat' AND p."Name" = 'check'""",
        seeded_env,
    )
    assert default == '"exists"'


def test_reseed_is_idempotent_and_keeps_catalog_schemas(seeded_env: dict[str, str]) -> None:
    before = _psql(
        """SELECT string_agg(p.ctid::text, ',' ORDER BY p."MethodID", p."Ordinal")
           FROM "Meta"."MethodParams" p JOIN "Meta"."Methods" m ON m."ID" = p."MethodID"
           WHERE m."ImplRef" LIKE 'workflow.%'""",
        seeded_env,
    )
    schemas_before = _psql(
        "SELECT count(*) || ':' || coalesce(md5(string_agg(s.schema_json::text, '' ORDER BY s.workflow_action_id, s.direction)), '')"
        " FROM wf.workflow_action_schema s JOIN wf.workflow_action a ON a.id = s.workflow_action_id"
        " WHERE a.action_name LIKE 'workflow.%'",
        seeded_env,
    )
    assert _psql('SELECT "Meta".sp_seed_platform_action_methods()', seeded_env) == str(len(EXPECTED))
    after = _psql(
        """SELECT string_agg(p.ctid::text, ',' ORDER BY p."MethodID", p."Ordinal")
           FROM "Meta"."MethodParams" p JOIN "Meta"."Methods" m ON m."ID" = p."MethodID"
           WHERE m."ImplRef" LIKE 'workflow.%'""",
        seeded_env,
    )
    assert before == after
    schemas_after = _psql(
        "SELECT count(*) || ':' || coalesce(md5(string_agg(s.schema_json::text, '' ORDER BY s.workflow_action_id, s.direction)), '')"
        " FROM wf.workflow_action_schema s JOIN wf.workflow_action a ON a.id = s.workflow_action_id"
        " WHERE a.action_name LIKE 'workflow.%'",
        seeded_env,
    )
    assert schemas_before == schemas_after


def test_seed_function_is_not_callable_by_portal(seeded_env: dict[str, str]) -> None:
    allowed = _psql(
        "SELECT has_function_privilege('goliath_portal', '\"Meta\".sp_seed_platform_action_methods()', 'EXECUTE')",
        seeded_env,
    )
    assert allowed == "f"
