"""Engine-level action catalog (platform workflow compute primitives)."""

from __future__ import annotations

from goliath_app.actions.spec import ActionLevel, ActionSpec
from goliath_app.engine.models import (
    ConstBoolInput,
    ConstBoolOutput,
    ConstIntInput,
    ConstIntOutput,
    ConstPathInput,
    ConstPathOutput,
    ConstStringInput,
    ConstStringOutput,
    FsStatInput,
    FsStatOutput,
    JsonPathInput,
    JsonPathBoolOutput,
    JsonPathIntOutput,
    JsonPathStringOutput,
)

_SCHEMA_VERSION = "1"


def _engine_spec(
    action_name: str,
    display_name: str,
    description: str,
    input_model: type,
    output_model: type,
    handler_name: str,
) -> ActionSpec:
    return ActionSpec(
        action_name=action_name,
        namespace="engine",
        level=ActionLevel.ENGINE,
        entity_code="workflow",
        display_name=display_name,
        description=description,
        input_model=input_model,
        output_model=output_model,
        schema_version=_SCHEMA_VERSION,
        capability="workflow.compute",
        tool="workflow.compute",
        in_process_handler=handler_name,
    )


ACTION_CATALOG = [
    _engine_spec(
        "workflow.const_bool",
        "Constant bool",
        "Assign a boolean literal into workflow scope",
        ConstBoolInput,
        ConstBoolOutput,
        "goliath_app.engine.handlers:handle_const_bool",
    ),
    _engine_spec(
        "workflow.const_int",
        "Constant int",
        "Assign an integer literal into workflow scope",
        ConstIntInput,
        ConstIntOutput,
        "goliath_app.engine.handlers:handle_const_int",
    ),
    _engine_spec(
        "workflow.const_string",
        "Constant string",
        "Assign a string literal into workflow scope",
        ConstStringInput,
        ConstStringOutput,
        "goliath_app.engine.handlers:handle_const_string",
    ),
    _engine_spec(
        "workflow.const_path",
        "Constant path",
        "Assign a filesystem path literal into workflow scope",
        ConstPathInput,
        ConstPathOutput,
        "goliath_app.engine.handlers:handle_const_path",
    ),
    _engine_spec(
        "workflow.json_path_bool",
        "JSON path bool",
        "Read a boolean from a JSON document using a JSONPath-like selector",
        JsonPathInput,
        JsonPathBoolOutput,
        "goliath_app.engine.handlers:handle_json_path_bool",
    ),
    _engine_spec(
        "workflow.json_path_int",
        "JSON path int",
        "Read an integer from a JSON document using a JSONPath-like selector",
        JsonPathInput,
        JsonPathIntOutput,
        "goliath_app.engine.handlers:handle_json_path_int",
    ),
    _engine_spec(
        "workflow.json_path_string",
        "JSON path string",
        "Read a string from a JSON document using a JSONPath-like selector",
        JsonPathInput,
        JsonPathStringOutput,
        "goliath_app.engine.handlers:handle_json_path_string",
    ),
    _engine_spec(
        "workflow.fs_stat",
        "Filesystem stat",
        "Test whether a path exists or is a file/directory",
        FsStatInput,
        FsStatOutput,
        "goliath_app.engine.handlers:handle_fs_stat",
    ),
]
