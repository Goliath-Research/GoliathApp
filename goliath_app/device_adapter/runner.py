"""Process wrapper: gateway client + optional periodic heartbeat events (workflow schedule owns real cron)."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from goliath_worker.client import WorkflowRestClient

from goliath_app.device_adapter.base import DeviceAdapterBase
from goliath_app.device_adapter.contract import utc_now_iso
from goliath_app.device_adapter.gateway_transport import GatewayEventTransport


@dataclass(frozen=True)
class AdapterProcessConfig:
    worker_id: int
    worker_token: str
    event_source: str
    heartbeat_interval_seconds: float = 0.0
    wake_http: bool = True


def run_adapter_process(
    adapter: DeviceAdapterBase,
    transport: GatewayEventTransport,
    *,
    cfg: AdapterProcessConfig,
    blocking_fn: Callable[[], None],
    stop_event: Optional[threading.Event] = None,
) -> None:
    """
    Run ``blocking_fn`` (typically protocol ``loop_forever``) and optionally emit
    periodic heartbeat events for observability. **Scheduling** belongs in
    workflow definitions (``WAIT_TIMER`` / capability-scoped tasks); this is
    only a coarse process-level pulse when you do not yet have a scheduled graph.
    """
    if cfg.wake_http:
        os.environ.setdefault("WORKER_WAKE_HTTP", "1")

    halt = stop_event or threading.Event()

    def _beat_loop() -> None:
        if cfg.heartbeat_interval_seconds <= 0:
            return
        while not halt.is_set():
            time.sleep(cfg.heartbeat_interval_seconds)
            if halt.is_set():
                break
            payload = {
                "adapter_id": adapter.config.adapter_id,
                "contract_version": adapter.config.contract_version,
                "device_key": adapter.config.device_key,
                "organization_key": adapter.config.organization_key,
                "emitted_at_utc": utc_now_iso(),
            }
            key_material = json.dumps(
                {"src": "heartbeat", "adapter": adapter.config.adapter_id, "t": int(time.time())},
                sort_keys=True,
            )
            ikey = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:48]
            transport.ingest(
                cfg.worker_id,
                cfg.worker_token,
                event_type="device.adapter.heartbeat.v1",
                source=cfg.event_source,
                idempotency_key=ikey,
                payload=payload,
            )

    beat = threading.Thread(target=_beat_loop, name="adapter-heartbeat", daemon=True)
    if cfg.heartbeat_interval_seconds > 0:
        beat.start()
    try:
        blocking_fn()
    finally:
        halt.set()


def open_gateway_client() -> WorkflowRestClient:
    """Shared gateway client from ``GOLIATH_API_BASE`` / ``resolve_api_base``."""
    return WorkflowRestClient()
