"""Abstract device adapter — extend hooks; keep domain logic in child repos."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field

from goliath_app.device_adapter.contract import (
    ADAPTER_CONTRACT_VERSION,
    AdapterCapability,
    DeviceNormalizedEvent,
    SafetyDecision,
)


class DeviceAdapterConfig(BaseModel):
    """Host-resolved configuration (secret refs, not inline tokens)."""

    model_config = ConfigDict(extra="forbid")

    adapter_id: str
    contract_version: str = ADAPTER_CONTRACT_VERSION
    capabilities: tuple[AdapterCapability, ...] = ()
    organization_key: str = Field(
        default="",
        description="Tenancy label bound at deploy time; do not trust protocol payloads for this.",
    )
    device_key: str = Field(
        default="",
        description="Stable device identity for correlation in workflow payloads.",
    )


class DeviceAdapterBase(ABC):
    """Gateway extension: translate protocol → normalized events; optional command safety."""

    def __init__(self, config: DeviceAdapterConfig) -> None:
        self._config = config

    @property
    def config(self) -> DeviceAdapterConfig:
        return self._config

    @abstractmethod
    def normalized_event_sources(self) -> tuple[str, ...]:
        """Return ``source`` strings used in ``POST /v1/events`` (for ops filtering)."""

    @abstractmethod
    def translate_to_events(self, raw_message: Any) -> Iterable[DeviceNormalizedEvent]:
        """Map one protocol message to zero or more engine events."""

    def safety_gate_command(self, raw_command: Any) -> SafetyDecision:
        """Default deny for actuation; override in child repos with policy."""
        _ = raw_command
        return SafetyDecision(allowed=False, reason="default deny: actuation disabled in base adapter")

    def on_transport_connected(self) -> None:
        """Hook after successful protocol connection (TLS/session)."""

    def on_transport_disconnected(self, reason: str) -> None:
        """Hook after disconnect or transport error."""

    def subscription_specs(self) -> list[dict[str, Any]]:
        """Optional subscription hints for runners (topics, entity globs, etc.)."""
        return []
