"""Dispatch registered actions in-process using typed Pydantic models."""

from __future__ import annotations

import importlib
from typing import Any, Dict, Mapping, Type

from pydantic import BaseModel

from goliath_app.actions.registry import find_action
from goliath_app.engine.handlers import handler_for as engine_handler_for


def _load_handler(dotted: str):
    module_name, func_name = dotted.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, func_name)


def normalize_action_input(
    action_name: str,
    capability: str,
    input_json: Mapping[str, Any],
) -> BaseModel:
    spec = find_action(action_name)
    if spec is None:
        raise KeyError(f"unknown action {action_name!r}")
    data = dict(input_json)
    if "tool" not in data:
        data["tool"] = spec.resolved_tool
    return spec.input_model.model_validate(data)


def validate_action_output(
    action_name: str,
    capability: str,
    output: BaseModel,
) -> BaseModel:
    spec = find_action(action_name)
    if spec is None:
        raise KeyError(f"unknown action {action_name!r}")
    if not isinstance(output, spec.output_model):
        return spec.output_model.model_validate(output.model_dump(mode="python"))
    return output


def execute_action(
    capability: str,
    action_name: str,
    input_json: Mapping[str, Any],
) -> BaseModel:
    spec = find_action(action_name)
    if spec is None:
        raise KeyError(f"unknown action {action_name!r}")
    model = normalize_action_input(action_name, capability, input_json)
    handler = engine_handler_for(action_name)
    if handler is None and spec.in_process_handler:
        handler = _load_handler(spec.in_process_handler)
    if handler is None:
        raise RuntimeError(f"no in-process handler registered for {action_name!r}")
    result = handler(model)
    return validate_action_output(action_name, capability, result)
