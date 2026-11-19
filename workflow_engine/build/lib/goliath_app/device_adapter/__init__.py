"""Shared device-adapter foundation (gateway-only transport, no worker SQL)."""

from goliath_app.device_adapter.base import DeviceAdapterBase
from goliath_app.device_adapter.contract import (
    ADAPTER_CONTRACT_VERSION,
    AdapterCapability,
    CommandIntent,
    DeviceNormalizedEvent,
    DeviceReading,
    SafetyDecision,
)
from goliath_app.device_adapter.gateway_transport import GatewayEventTransport
from goliath_app.device_adapter.runner import AdapterProcessConfig, run_adapter_process

__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "AdapterCapability",
    "AdapterProcessConfig",
    "CommandIntent",
    "DeviceAdapterBase",
    "DeviceNormalizedEvent",
    "DeviceReading",
    "GatewayEventTransport",
    "SafetyDecision",
    "run_adapter_process",
]
