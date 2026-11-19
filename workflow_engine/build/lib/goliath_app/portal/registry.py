"""Map semantic request codes to Pydantic param and row models."""

from __future__ import annotations

from typing import Mapping, Type

from pydantic import BaseModel

from goliath_app.semantic.catalog import SEMANTIC_REQUESTS
from goliath_app.semantic.spec import SemanticRequestSpec

SEMANTIC_REQUEST_BY_CODE: Mapping[str, SemanticRequestSpec] = {
    spec.request_code: spec for spec in SEMANTIC_REQUESTS
}


def params_model_for(request_code: str) -> Type[BaseModel]:
    try:
        return SEMANTIC_REQUEST_BY_CODE[request_code].params_model
    except KeyError:
        raise KeyError(f"unknown semantic request_code: {request_code}") from None


def result_model_for(request_code: str) -> Type[BaseModel]:
    try:
        return SEMANTIC_REQUEST_BY_CODE[request_code].result_row_model
    except KeyError:
        raise KeyError(f"unknown semantic request_code: {request_code}") from None
