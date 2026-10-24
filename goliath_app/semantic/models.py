"""Core semantic row and parameter models."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class OrganizationRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    organization_id: int
    name: str
    active: bool


class ListOrganizationsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: Optional[int] = None
    limit: Optional[PositiveInt] = Field(default=None, le=500)


class FilterOrganizationsParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    limit: Optional[PositiveInt] = Field(default=None, le=500)
