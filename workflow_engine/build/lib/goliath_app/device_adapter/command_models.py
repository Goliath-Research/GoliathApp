"""Typed workflow I/O for generic device-adapter command relay (simulation-friendly)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

class DeviceAdapterCommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_key: str = Field(description="Stable command name (child apps interpret)")
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(description="Workflow-scoped idempotency token")
    correlation_key: str = Field(default="", description="Optional workflow correlation")
    timeout_seconds: float = Field(default=30.0, ge=0.0, le=3600.0)
    target: dict[str, Any] = Field(
        default_factory=dict,
        description="Adapter-specific target hint (e.g. mqtt_topic, ha_service); never trusted for org scope",
    )


AckKind = Literal["protocol_accepted", "physical_pending", "physical_confirmed", "rejected"]


class DeviceAdapterCommandOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ack_kind: AckKind = Field(
        description="protocol_accepted: broker/HA accepted only; never conflate with physical_confirmed"
    )
    detail: str = ""
    simulated: bool = True


class DeviceAdapterObserveInput(BaseModel):
    """In-workflow observe step: adapter process fills output after protocol read (claimed task)."""

    model_config = ConfigDict(extra="forbid")

    observe_key: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


class DeviceAdapterObserveOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    readings: list[dict[str, Any]] = Field(default_factory=list)
    simulated: bool = True
