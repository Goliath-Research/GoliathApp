"""Meta catalog validation helpers (Phase D — pydantic layer over class JSON Schema)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, create_model


def pydantic_model_from_class_schema(schema: dict[str, Any]) -> type[BaseModel]:
    """Build a strict Pydantic model from a Meta class schema fragment (own properties)."""
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    field_defs: dict[str, Any] = {}
    for name in props:
        if name in required:
            field_defs[name] = (Any, ...)
        else:
            field_defs[name] = (Any, None)
    return create_model(
        "MetaCatalogObject",
        __config__=ConfigDict(extra="forbid"),
        **field_defs,
    )


def validate_meta_document(schema: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    model = pydantic_model_from_class_schema(schema)
    return model.model_validate(document).model_dump(mode="json")
