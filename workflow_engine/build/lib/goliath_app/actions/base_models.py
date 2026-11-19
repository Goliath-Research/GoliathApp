"""Shared typed fields for workflow action I/O models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ActionOutputBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_code: int = Field(default=0, description="0 = success")


class BoolValueOutput(ActionOutputBase):
    value: bool


class IntValueOutput(ActionOutputBase):
    value: int


class StringValueOutput(ActionOutputBase):
    value: str
