"""Pydantic models for engine-namespace workflow compute actions."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from goliath_app.actions.base_models import BoolValueOutput, IntValueOutput, StringValueOutput


class EngineActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(default="workflow.compute")


class ConstBoolInput(EngineActionInput):
    value: bool


class ConstIntInput(EngineActionInput):
    value: int


class ConstStringInput(EngineActionInput):
    value: str


class ConstPathInput(EngineActionInput):
    value: str = Field(description="Filesystem path literal")


class JsonPathInput(EngineActionInput):
    document: dict[str, object] = Field(default_factory=dict)
    json_path: str = Field(alias="jsonPath")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class FsStatInput(EngineActionInput):
    path: str
    check: str = Field(default="exists", description="exists | is_file | is_dir")


class ConstBoolOutput(BoolValueOutput):
    pass


class ConstIntOutput(IntValueOutput):
    pass


class ConstStringOutput(StringValueOutput):
    pass


class ConstPathOutput(StringValueOutput):
    pass


class JsonPathBoolOutput(BoolValueOutput):
    pass


class JsonPathIntOutput(IntValueOutput):
    pass


class JsonPathStringOutput(StringValueOutput):
    pass


class FsStatOutput(BoolValueOutput):
    detail: Optional[str] = None
