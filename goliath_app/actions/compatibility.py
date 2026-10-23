"""Override compatibility checks for action catalog registration."""

from __future__ import annotations

from typing import Any, Mapping, Type

from pydantic import BaseModel

from goliath_app.actions.spec import ActionSpec


def _model_json_schema(model: Type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema(mode="serialization")


def _required_keys(schema: Mapping[str, Any]) -> set[str]:
    return set(schema.get("required") or [])


def _properties(schema: Mapping[str, Any]) -> dict[str, Any]:
    props = schema.get("properties")
    return dict(props) if isinstance(props, dict) else {}


def input_schema_compatible(base: Type[BaseModel], derived: Type[BaseModel]) -> bool:
    """Derived input may add optional fields or tighten constraints on existing fields."""
    if not issubclass(derived, base):
        return False
    base_schema = _model_json_schema(base)
    derived_schema = _model_json_schema(derived)
    base_req = _required_keys(base_schema)
    derived_req = _required_keys(derived_schema)
    if not base_req.issubset(derived_req):
        return False
    base_props = _properties(base_schema)
    derived_props = _properties(derived_schema)
    for name in base_props:
        if name not in derived_props:
            return False
    # New properties must be optional. A required key that the base does not
    # declare would reject callers that already omit it.
    if not derived_req.issubset(set(base_props)):
        return False
    return True


def output_schema_compatible(base: Type[BaseModel], derived: Type[BaseModel]) -> bool:
    """Derived output may only add fields."""
    if not issubclass(derived, base):
        return False
    base_props = set(_properties(_model_json_schema(base)))
    derived_props = set(_properties(_model_json_schema(derived)))
    return base_props.issubset(derived_props)


def assert_override_compatible(base: ActionSpec, override: ActionSpec) -> None:
    if override.overrides is None:
        raise ValueError(
            f"override {override.action_name!r} must set overrides= to the base namespace"
        )
    if override.overrides != base.namespace:
        raise ValueError(
            f"override {override.action_name!r} targets namespace {override.overrides!r}, "
            f"expected {base.namespace!r}"
        )
    if override.action_name != base.action_name:
        raise ValueError("override must keep the same action_name as the base action")
    if not input_schema_compatible(base.input_model, override.input_model):
        raise ValueError(
            f"input_model for {override.action_name!r} is not a compatible override of core"
        )
    if not output_schema_compatible(base.output_model, override.output_model):
        raise ValueError(
            f"output_model for {override.action_name!r} is not a compatible override of core"
        )
