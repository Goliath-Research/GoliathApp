"""Typed filter templates for semantic read requests."""

from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class FilterOp(str, Enum):
    EQ = "eq"
    IN = "in"
    BETWEEN = "between"
    GTE = "gte"
    LTE = "lte"
    STARTS_WITH = "starts_with"
    IS_NULL = "is_null"


class Predicate(BaseModel):
    model_config = ConfigDict(frozen=True)

    attribute: str
    op: FilterOp
    param: str | None = None


class FilterTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    all_of: List[Predicate] = Field(default_factory=list)
