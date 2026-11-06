"""Home Assistant WebSocket + REST reference adapter (MIT-licensed Home Assistant API surface)."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from pydantic import ConfigDict, Field

from goliath_app.device_adapter.base import DeviceAdapterBase, DeviceAdapterConfig
from goliath_app.device_adapter.contract import DeviceNormalizedEvent, SafetyDecision
from goliath_app.device_adapter.secrets import SecretRef, read_secret_ref


class HomeAssistantAdapterConfig(DeviceAdapterConfig):
    model_config = ConfigDict(extra="forbid")

    base_url: str = "http://127.0.0.1:8123"
    token_ref: SecretRef
    entity_allowlist: tuple[str, ...] = Field(
        default=(),
        description="Non-empty required to emit state_changed events (fail closed).",
    )
    service_allowlist: tuple[str, ...] = Field(
        default=(),
        description="domain.service entries permitted for command relay (default none).",
    )
    verify_tls: bool = True


class HomeAssistantDeviceAdapter(DeviceAdapterBase):
    def __init__(self, cfg: HomeAssistantAdapterConfig) -> None:
        super().__init__(cfg)
        self._ha = cfg
        self._msg_id = 1

    def normalized_event_sources(self) -> tuple[str, ...]:
        return (f"homeassistant:{self._ha.adapter_id}",)

    def translate_to_events(self, raw_message: Any) -> Iterable[DeviceNormalizedEvent]:
        if not isinstance(raw_message, dict):
            return ()
        event = raw_message.get("event") or raw_message
        if not isinstance(event, dict):
            return ()
        if event.get("event_type") != "state_changed":
            return ()
        data = event.get("data") or {}
        entity_id = str(data.get("entity_id") or "")
        if self._ha.entity_allowlist and entity_id not in self._ha.entity_allowlist:
            return ()
        if not self._ha.entity_allowlist:
            return ()
        new_state = data.get("new_state") or {}
        payload = {
            "organization_key": self.config.organization_key,
            "device_key": self.config.device_key,
            "entity_id": entity_id,
            "state": new_state.get("state"),
            "attributes": new_state.get("attributes") if isinstance(new_state.get("attributes"), dict) else {},
            "last_changed": new_state.get("last_changed"),
            "last_updated": new_state.get("last_updated"),
        }
        return (DeviceNormalizedEvent(event_type="device.homeassistant.state_changed.v1", payload=payload),)

    def safety_gate_command(self, raw_command: Any) -> SafetyDecision:
        _ = raw_command
        return SafetyDecision(allowed=False, reason="HA service calls disabled by default (fail closed)")

    def rest_get_states(self, token: str) -> list[dict[str, Any]]:
        url = self._ha.base_url.rstrip("/") + "/api/states"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        ctx: ssl.SSLContext | None = None
        parsed = urlparse(self._ha.base_url)
        if parsed.scheme == "https" and not self._ha.verify_tls:
            ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        return data if isinstance(data, list) else []

    def iter_websocket_events(
        self,
        *,
        token: str,
        on_event: Any,
    ) -> None:
        import websocket

        parsed = urlparse(self._ha.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        netloc = parsed.netloc or parsed.path
        path = "/api/websocket"
        ws_url = f"{scheme}://{netloc}{path}"

        connect_kw: dict[str, Any] = {"timeout": 30}
        if scheme == "wss" and not self._ha.verify_tls:
            connect_kw["sslopt"] = {"cert_reqs": ssl.CERT_NONE}

        ws = websocket.create_connection(ws_url, **connect_kw)

        def expect_json() -> dict[str, Any]:
            raw = ws.recv()
            if not isinstance(raw, str):
                raw = raw.decode("utf-8")
            return json.loads(raw)

        hello = expect_json()
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"unexpected WS hello: {hello!r}")

        ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth = expect_json()
        if auth.get("type") != "auth_ok":
            raise RuntimeError("HA websocket authentication failed")

        self.on_transport_connected()
        sub_id = self._msg_id
        self._msg_id += 1
        ws.send(
            json.dumps(
                {
                    "id": sub_id,
                    "type": "subscribe_events",
                    "event_type": "state_changed",
                }
            )
        )
        while True:
            msg = expect_json()
            if msg.get("type") == "result" and int(msg.get("id", 0)) == sub_id:
                if not msg.get("success", True):
                    raise RuntimeError(f"subscribe_events failed: {msg!r}")
                break
        while True:
            msg = expect_json()
            if msg.get("type") == "event":
                on_event(msg)


def ha_main() -> None:
    from goliath_app.device_adapter.gateway_transport import GatewayEventTransport
    from goliath_app.device_adapter.runner import AdapterProcessConfig, open_gateway_client, run_adapter_process

    cfg_json = os.environ.get("GOLIATH_HA_ADAPTER_CONFIG", "").strip()
    if not cfg_json:
        raise SystemExit("Set GOLIATH_HA_ADAPTER_CONFIG to JSON for HomeAssistantAdapterConfig")
    ha_cfg = HomeAssistantAdapterConfig.model_validate_json(cfg_json)
    token = read_secret_ref(ha_cfg.token_ref)
    if not token:
        raise SystemExit("token_ref did not resolve to a non-empty secret")
    worker_id = int(os.environ["GOLIATH_ADAPTER_WORKER_ID"])
    worker_token = os.environ["GOLIATH_ADAPTER_WORKER_TOKEN"]
    client = open_gateway_client()
    if os.environ.get("GOLIATH_ADAPTER_OPEN_SESSION", "").lower() in ("1", "true", "yes"):
        client.open_session(worker_token)
    transport = GatewayEventTransport(client)
    adapter = HomeAssistantDeviceAdapter(ha_cfg)
    source = adapter.normalized_event_sources()[0]
    seen: set[str] = set()
    lock = threading.Lock()

    def ingest(ev: DeviceNormalizedEvent, dedupe_material: str) -> None:
        ikey = hashlib.sha256(dedupe_material.encode("utf-8")).hexdigest()[:56]
        with lock:
            if ikey in seen:
                return
            seen.add(ikey)
        transport.ingest(
            worker_id,
            worker_token,
            event_type=ev.event_type,
            source=source,
            idempotency_key=f"ha:{ha_cfg.adapter_id}:{ikey}",
            payload=ev.payload,
        )

    def handle_ws(msg: dict[str, Any]) -> None:
        for ev in adapter.translate_to_events(msg):
            raw_event = msg.get("event") or {}
            data = (raw_event.get("data") or {}) if isinstance(raw_event, dict) else {}
            entity = str(data.get("entity_id") or "")
            new_state = data.get("new_state") or {}
            last_updated = str(new_state.get("last_updated") or "")
            mat = f"{entity}|{last_updated}|{json.dumps(new_state.get('state'), sort_keys=True)}"
            ingest(ev, mat)

    def poll_loop() -> None:
        while True:
            time.sleep(float(os.environ.get("GOLIATH_HA_POLL_SECONDS", "60")))
            try:
                states = adapter.rest_get_states(token)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                adapter.on_transport_disconnected("rest_poll_failed")
                continue
            for st in states:
                eid = str(st.get("entity_id") or "")
                if ha_cfg.entity_allowlist and eid not in ha_cfg.entity_allowlist:
                    continue
                if not ha_cfg.entity_allowlist:
                    continue
                fake = {
                    "event": {
                        "event_type": "state_changed",
                        "data": {
                            "entity_id": eid,
                            "new_state": st,
                        },
                    }
                }
                handle_ws(fake)

    def blocking() -> None:
        poll_thread = threading.Thread(target=poll_loop, name="ha-rest-poll", daemon=True)
        poll_thread.start()
        adapter.iter_websocket_events(token=token, on_event=handle_ws)

    proc = AdapterProcessConfig(
        worker_id=worker_id,
        worker_token=worker_token,
        event_source=source,
        heartbeat_interval_seconds=float(os.environ.get("GOLIATH_ADAPTER_HEARTBEAT_SECONDS", "0") or 0),
    )

    run_adapter_process(adapter, transport, cfg=proc, blocking_fn=blocking)
