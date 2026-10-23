"""Platform action catalog: plugins, typing, and override rules."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from goliath_app.actions.compatibility import assert_override_compatible
from goliath_app.actions.registry import find_action, load_action_catalog, reload_action_catalog
from goliath_app.actions.schema_export import export_catalog_document
from goliath_app.actions.spec import ActionLevel, ActionSpec
from goliath_app.core.models import PlanIterationsInput, PlanIterationsOutput
from goliath_app.execution.local import execute_action

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = (
    REPO_ROOT / "goliath_app",
    REPO_ROOT / "workflow_engine" / "domain" / "action_catalog.py",
    REPO_ROOT / "workflow_engine" / "local" / "engine.py",
    REPO_ROOT / "workflow_engine" / "local" / "foreach_caas.py",
    REPO_ROOT / "workflow_engine" / "rest" / "execution_scope.py",
)

FORBIDDEN_APP_PREFIXES = ("methyl_worker", "methyl_domain", "methyl_utils", "methyl_enricher")


def _iter_files() -> list[Path]:
    paths: list[Path] = []
    for root in SCAN_ROOTS:
        if root.is_file():
            paths.append(root)
        else:
            paths.extend(root.rglob("*.py"))
    return paths


def test_no_app_package_imports_in_platform_catalog_surface() -> None:
    offenders: list[str] = []
    for path in _iter_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in FORBIDDEN_APP_PREFIXES:
                        offenders.append(f"{path}:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in FORBIDDEN_APP_PREFIXES:
                    offenders.append(f"{path}:{node.module}")
    assert not offenders, "app package imports found: " + ", ".join(offenders)


def test_catalog_has_engine_and_core_actions() -> None:
    reload_action_catalog()
    names = {spec.action_name for spec in load_action_catalog()}
    assert "workflow.const_bool" in names
    assert "validation.plan_iterations" in names
    engine = find_action("workflow.const_bool")
    assert engine is not None
    assert engine.level == ActionLevel.ENGINE
    assert engine.resolved_exposure.value == "hidden"


def test_normalize_strips_scheduler_injected_fields() -> None:
    from goliath_app.execution.local import normalize_action_input

    model = normalize_action_input(
        "workflow.const_bool",
        "workflow.compute",
        {
            "tool": "workflow.compute",
            "value": False,
            "projectPath": "/tmp/x",
            "executionScopeId": "scope-1",
            "workflowNodeKey": "n1",
            "forceRerun": True,
        },
    )
    assert model.value is False


def test_engine_action_executes_with_typed_models() -> None:
    from goliath_app.engine.models import ConstBoolOutput

    output = execute_action(
        "workflow.compute",
        "workflow.const_bool",
        {"tool": "workflow.compute", "value": True},
    )
    assert isinstance(output, ConstBoolOutput)
    assert output.value is True


def _field_types(model: type[BaseModel]) -> list[Any]:
    return [field.annotation for field in model.model_fields.values()]


def test_action_spec_models_have_no_any_in_fields() -> None:
    for spec in load_action_catalog():
        for annotation in _field_types(spec.input_model) + _field_types(spec.output_model):
            if annotation is Any:
                raise AssertionError(f"Any field in {spec.action_name}")
            if getattr(annotation, "__name__", "") == "Any":
                raise AssertionError(f"Any field in {spec.action_name}")


def test_override_rejects_new_required_input_fields() -> None:
    from goliath_app.actions.compatibility import input_schema_compatible

    base = find_action("validation.plan_iterations")
    assert base is not None

    class BadInput(PlanIterationsInput):
        required_extra: str

    assert not input_schema_compatible(base.input_model, BadInput)


def test_override_compatibility_accepts_subclass_models() -> None:
    base = find_action("validation.plan_iterations")
    assert base is not None

    class ExtendedPlanInput(PlanIterationsInput):
        extra_note: str | None = None

    class ExtendedPlanOutput(PlanIterationsOutput):
        planner_version: str = "omics-1"

    override = ActionSpec(
        action_name=base.action_name,
        namespace="omics",
        level=base.level,
        entity_code=base.entity_code,
        display_name=base.display_name,
        description=base.description,
        required_permission=base.required_permission,
        input_model=ExtendedPlanInput,
        output_model=ExtendedPlanOutput,
        schema_version="2",
        overrides="core",
    )
    assert_override_compatible(base, override)


def test_schema_export_document_contains_hashes() -> None:
    doc = export_catalog_document()
    action = doc["actions"]["workflow.const_bool"]
    assert action["schemas"]["input"]["content_hash"]
    assert action["schemas"]["output"]["content_hash"]
