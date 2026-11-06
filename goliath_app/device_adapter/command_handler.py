"""Generic command safety + simulation hook for claimed adapter tasks."""

from __future__ import annotations

import importlib
import os
import time
from typing import Any

from goliath_app.device_adapter.command_models import (
    DeviceAdapterCommandInput,
    DeviceAdapterCommandOutput,
    DeviceAdapterObserveInput,
    DeviceAdapterObserveOutput,
)


def default_command_safety(inp: DeviceAdapterCommandInput) -> DeviceAdapterCommandOutput:
    """
    Platform default: deny all actuation. Child adapters override via module path
    in workflow action argv_map or dedicated executor process — not a second framework.
    """
    _ = inp
    return DeviceAdapterCommandOutput(ack_kind="rejected", detail="default deny: no actuation policy", simulated=True)


def handle_device_adapter_command(inp: DeviceAdapterCommandInput) -> DeviceAdapterCommandOutput:
    """Entry point registered on ``workflow.device_adapter.command``."""
    hook = os.environ.get("GOLIATH_ADAPTER_COMMAND_SAFETY", "").strip()
    if hook:
        mod_path, _, func = hook.partition(":")
        if mod_path and func:
            mod = importlib.import_module(mod_path)
            fn = getattr(mod, func)
            out = fn(inp)
            if isinstance(out, DeviceAdapterCommandOutput):
                return out
    return default_command_safety(inp)


def handle_device_adapter_observe(inp: DeviceAdapterObserveInput) -> DeviceAdapterObserveOutput:
    """Simulated observe for integration tests; real adapters replace via executor env."""
    _ = inp.observe_key
    return DeviceAdapterObserveOutput(
        readings=[{"value": "simulated", "quality": "sim"}],
        simulated=True,
    )


def sleep_until_deadline(deadline_monotonic: float) -> None:
    while time.monotonic() < deadline_monotonic:
        time.sleep(0.05)
