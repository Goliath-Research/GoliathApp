"""Versioned, domain-neutral device-adapter contract (normative types for extensions)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Bump when normative JSON shapes or required hooks change.
ADAPTER_CONTRACT_VERSION = "1.0.0"


class AdapterCapability(str, Enum):
    """Declared adapter roles (subset; extend in child repos)."""

    TELEMETRY_INGEST = "telemetry.ingest"
    EVENT_INGEST = "event.ingest"
    COMMAND_RELAY = "command.relay"


class DeviceReading(BaseModel):
    """Single normalized sensor reading (protocol-agnostic)."""

    model_config = ConfigDict(extra="forbid")

    reading_key: str
    value: Any
    unit: Optional[str] = None
    quality: Optional[str] = None
    observed_at_utc: Optional[str] = None


class DeviceNormalizedEvent(BaseModel):
    """Canonical payload envelope for ``wf.sp_ingest_event`` (event_type + payload)."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = "device.telemetry.v1"
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandIntent(BaseModel):
    """Outbound command (may be rejected by safety before any protocol send)."""

    model_config = ConfigDict(extra="forbid")

    command_key: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    correlation_key: Optional[str] = None


class SafetyDecision(BaseModel):
    """Fail-closed gate for actuation (MQTT PUBACK / HA call ≠ physical ack)."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str = ""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


CommandAckKind = Literal["protocol_accepted", "physical_pending", "physical_confirmed", "rejected"]
