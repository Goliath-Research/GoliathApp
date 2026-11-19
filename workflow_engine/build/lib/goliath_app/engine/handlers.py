"""In-process handlers for engine-namespace actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from pydantic import BaseModel

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
    JsonPathBoolOutput,
    JsonPathInput,
    JsonPathIntOutput,
    JsonPathStringOutput,
)


def _json_path_get(document: Any, json_path: str) -> Any:
    if not json_path or json_path in ("$", "$."):
        return document
    path = json_path.lstrip("$").lstrip(".")
    if not path:
        return document
    current = document
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise KeyError(f"jsonPath segment {segment!r} missing")
        current = current[segment]
    return current


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    raise TypeError(f"cannot coerce {value!r} to bool")


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError("bool is not a valid int json path value")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise TypeError(f"cannot coerce {value!r} to int")


def handle_const_bool(inp: ConstBoolInput) -> ConstBoolOutput:
    return ConstBoolOutput(value=inp.value)


def handle_const_int(inp: ConstIntInput) -> ConstIntOutput:
    return ConstIntOutput(value=inp.value)


def handle_const_string(inp: ConstStringInput) -> ConstStringOutput:
    return ConstStringOutput(value=inp.value)


def handle_const_path(inp: ConstPathInput) -> ConstPathOutput:
    return ConstPathOutput(value=str(Path(inp.value)))


def handle_json_path_bool(inp: JsonPathInput) -> JsonPathBoolOutput:
    raw = _json_path_get(inp.document, inp.json_path)
    return JsonPathBoolOutput(value=_coerce_bool(raw))


def handle_json_path_int(inp: JsonPathInput) -> JsonPathIntOutput:
    raw = _json_path_get(inp.document, inp.json_path)
    return JsonPathIntOutput(value=_coerce_int(raw))


def handle_json_path_string(inp: JsonPathInput) -> JsonPathStringOutput:
    raw = _json_path_get(inp.document, inp.json_path)
    return JsonPathStringOutput(value=str(raw))


def handle_fs_stat(inp: FsStatInput) -> FsStatOutput:
    target = Path(inp.path)
    check = inp.check.strip().lower()
    if check == "exists":
        ok = target.exists()
    elif check == "is_file":
        ok = target.is_file()
    elif check == "is_dir":
        ok = target.is_dir()
    else:
        raise ValueError(f"unsupported fs_stat check {inp.check!r}")
    return FsStatOutput(value=ok, detail=check)


HANDLERS: Dict[str, Callable[..., BaseModel]] = {
    "workflow.const_bool": handle_const_bool,
    "workflow.const_int": handle_const_int,
    "workflow.const_string": handle_const_string,
    "workflow.const_path": handle_const_path,
    "workflow.json_path_bool": handle_json_path_bool,
    "workflow.json_path_int": handle_json_path_int,
    "workflow.json_path_string": handle_json_path_string,
    "workflow.fs_stat": handle_fs_stat,
}


def handler_for(action_name: str) -> Callable[..., BaseModel] | None:
    return HANDLERS.get(action_name)
