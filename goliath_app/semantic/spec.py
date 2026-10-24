"""Semantic registry metadata (Pydantic v2)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Type

from pydantic import BaseModel

from goliath_app.semantic.filters import FilterTemplate


@dataclass(frozen=True)
class SemanticAttributeSpec:
    code: str
    column_name: str
    json_type: str
    role: str
    filterable_ops: Sequence[str] = ()


@dataclass(frozen=True)
class SemanticEntitySpec:
    namespace: str
    code: str
    display_name: str
    description: str
    schema_version: str
    row_model: Type[BaseModel]
    storage_relation: Optional[str] = None
    attributes: Sequence[SemanticAttributeSpec] = ()


@dataclass(frozen=True)
class SemanticRequestSpec:
    request_code: str
    version: str
    namespace: str
    entity_code: str
    target_kind: str
    target_name: str
    params_model: Type[BaseModel]
    result_row_model: Type[BaseModel]
    filter_template: Optional[FilterTemplate] = None
    required_permission: Optional[str] = None
    max_rows: int = 500
    base_namespace: Optional[str] = None
