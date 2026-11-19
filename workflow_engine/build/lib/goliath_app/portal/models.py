"""Typed rows returned by portal session and semantic catalog procedures."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field


class SessionOpenResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_token: str
    session_id: int
    expires_at_utc: datetime


class SemanticCatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_code: str
    version: str
    namespace: str
    entity_code: str
    display_name: str
    params_schema: Mapping[str, object] = Field(default_factory=dict)
    result_schema: Mapping[str, object] = Field(default_factory=dict)
    required_permission: Optional[str] = None
