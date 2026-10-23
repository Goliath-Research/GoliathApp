"""Typed workflow action metadata (Pydantic v2)."""

from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field, model_validator

from goliath_app.actions.domain_effects import DomainEffects


class ActionLevel(str, Enum):
    ENGINE = "engine"
    CORE = "core"
    DOMAIN = "domain"


class ActionExposure(str, Enum):
    HIDDEN = "hidden"
    RBAC = "rbac"


class ActionSpec(BaseModel):
    """One registered workflow action with typed I/O models."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    action_name: str
    namespace: str
    level: ActionLevel
    entity_code: str
    display_name: str
    description: str
    exposure: Optional[ActionExposure] = None
    required_permission: Optional[str] = None
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    schema_version: str
    overrides: Optional[str] = Field(
        default=None,
        description="Base namespace when this row overrides a core action",
    )

    capability: str = ""
    tool: str = ""
    action_config_key: Optional[str] = None
    context_vars: Tuple[str, ...] = ()
    domain_effects: Optional[DomainEffects] = None
    in_process_handler: Optional[str] = None

    @model_validator(mode="after")
    def _validate_required_classification(self) -> ActionSpec:
        if not self.action_name.strip():
            raise ValueError("action_name is required")
        if not self.namespace.strip():
            raise ValueError("namespace is required")
        if not self.entity_code.strip():
            raise ValueError("entity_code is required")
        if not self.display_name.strip():
            raise ValueError("display_name is required")
        if not self.description.strip():
            raise ValueError("description is required")
        if not self.schema_version.strip():
            raise ValueError("schema_version is required")
        if self.input_model is None or self.output_model is None:
            raise ValueError("input_model and output_model are required")
        return self

    @property
    def resolved_exposure(self) -> ActionExposure:
        if self.exposure is not None:
            return self.exposure
        if self.level == ActionLevel.ENGINE:
            return ActionExposure.HIDDEN
        return ActionExposure.RBAC

    @property
    def resolved_capability(self) -> str:
        if self.capability:
            return self.capability
        return self.namespace

    @property
    def resolved_tool(self) -> str:
        if self.tool:
            return self.tool
        return self.action_name
