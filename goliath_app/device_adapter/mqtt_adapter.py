"""MQTT subscriber/publisher reference adapter (Eclipse Paho, Eclipse 2.0 / project license)."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
from typing import Any, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field

from goliath_app.device_adapter.base import DeviceAdapterBase, DeviceAdapterConfig
from goliath_app.device_adapter.contract import DeviceNormalizedEvent, SafetyDecision
from goliath_app.device_adapter.secrets import SecretRef, read_secret_ref


class MqttTopicRule(BaseModel):
    """Map ``topic_pattern`` to a JSON path or whole-payload reading."""

    model_config = ConfigDict(extra="forbid")

    topic_pattern: str
    idempotency_component: str = "topic+payload_hash"


class MqttAdapterConfig(DeviceAdapterConfig):
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    transport: str = "tcp"
    use_tls: bool = False
    tls_insecure: bool = False
    client_id: str = "goliath-mqtt-adapter"
    username: str = ""
    password_ref: Optional[SecretRef] = None
    subscribe_topics: tuple[str, ...] = Field(default=("#",))
    publish_topic_prefix: str = ""
    qos: int = 1
    topic_rules: tuple[MqttTopicRule, ...] = ()
    command_topic_allowlist: tuple[str, ...] = Field(
        default=(),
        description="Empty → fail closed for any actuation path.",
    )


class MqttDeviceAdapter(DeviceAdapterBase):
    def __init__(self, cfg: MqttAdapterConfig) -> None:
        super().__init__(cfg)
        self._mqtt_cfg = cfg

    def normalized_event_sources(self) -> tuple[str, ...]:
        return (f"mqtt:{self._mqtt_cfg.adapter_id}",)

    def translate_to_events(self, raw_message: Any) -> Iterable[DeviceNormalizedEvent]:
        """``raw_message`` is a dict: topic, payload (str|bytes), qos, retain, mid."""
        if not isinstance(raw_message, dict):
            return ()
        topic = str(raw_message.get("topic") or "")
        payload_raw = raw_message.get("payload") or b""
        if isinstance(payload_raw, str):
            body = payload_raw.encode("utf-8")
        else:
            body = bytes(payload_raw)
        try:
            obj = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            obj = {"raw_base64": body.hex()}

        h = hashlib.sha256(f"{topic}\0".encode("utf-8") + body).hexdigest()
        mid = raw_message.get("mid")
        event_payload = {
            "organization_key": self.config.organization_key,
            "device_key": self.config.device_key,
            "topic": topic,
            "payload": obj if isinstance(obj, dict) else {"value": obj},
            "mqtt": {"qos": raw_message.get("qos"), "retain": raw_message.get("retain"), "mid": mid},
            "dedupe_hint": h[:32],
        }
        return (
            DeviceNormalizedEvent(
                event_type="device.mqtt.message.v1",
                payload=event_payload,
            ),
        )

    def safety_gate_command(self, raw_command: Any) -> SafetyDecision:
        _ = raw_command
        return SafetyDecision(allowed=False, reason="MQTT actuation disabled by default (fail closed)")

    def build_paho_client(self) -> Any:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=self._mqtt_cfg.client_id,
            protocol=mqtt.MQTTv311,
        )
        pw = read_secret_ref(self._mqtt_cfg.password_ref)
        if self._mqtt_cfg.username or pw:
            client.username_pw_set(self._mqtt_cfg.username or None, pw)
        if self._mqtt_cfg.use_tls:
            ctx = ssl.create_default_context()
            client.tls_set_context(ctx)
            if self._mqtt_cfg.tls_insecure:
                client.tls_insecure_set(True)
        return client

    def iter_forever(self, *, on_message_dict: Any) -> None:
        import paho.mqtt.client as mqtt

        client = self.build_paho_client()

        def _on_connect(cli: Any, userdata: Any, flags: Any, rc: Any) -> None:
            _ = cli, userdata, flags
            if rc != 0:
                self.on_transport_disconnected(f"mqtt connect rc={rc}")
                return
            self.on_transport_connected()
            for t in self._mqtt_cfg.subscribe_topics:
                cli.subscribe(t, qos=self._mqtt_cfg.qos)

        def _on_message(cli: Any, userdata: Any, msg: Any) -> None:
            _ = cli, userdata
            raw = {
                "topic": msg.topic,
                "payload": msg.payload,
                "qos": msg.qos,
                "retain": msg.retain,
                "mid": getattr(msg, "mid", None),
            }
            on_message_dict(raw)

        client.on_connect = _on_connect
        client.on_message = _on_message
        client.connect(self._mqtt_cfg.broker_host, self._mqtt_cfg.broker_port, keepalive=60)
        client.loop_forever()

    @staticmethod
    def command_publish_topic_allowed(topic: str, allowlist: tuple[str, ...]) -> bool:
        if not allowlist:
            return False
        t = topic.strip()
        for p in allowlist:
            if p.endswith("#"):
                if t.startswith(p[:-1]):
                    return True
            elif t == p:
                return True
        return False


def mqtt_main() -> None:
    """Entry point: env-driven MQTT adapter (see docs/device-adapters.md)."""
    from goliath_app.device_adapter.gateway_transport import GatewayEventTransport
    from goliath_app.device_adapter.runner import AdapterProcessConfig, open_gateway_client, run_adapter_process

    cfg_json = os.environ.get("GOLIATH_MQTT_ADAPTER_CONFIG", "").strip()
    if not cfg_json:
        raise SystemExit("Set GOLIATH_MQTT_ADAPTER_CONFIG to JSON for MqttAdapterConfig")
    adapter_cfg = MqttAdapterConfig.model_validate_json(cfg_json)
    worker_id = int(os.environ["GOLIATH_ADAPTER_WORKER_ID"])
    worker_token = os.environ["GOLIATH_ADAPTER_WORKER_TOKEN"]
    client = open_gateway_client()
    if os.environ.get("GOLIATH_ADAPTER_OPEN_SESSION", "").lower() in ("1", "true", "yes"):
        client.open_session(worker_token)
    transport = GatewayEventTransport(client)

    adapter = MqttDeviceAdapter(adapter_cfg)

    def handle_raw(raw: dict[str, Any]) -> None:
        for ev in adapter.translate_to_events(raw):
            h = hashlib.sha256(
                json.dumps({"t": raw.get("topic"), "p": raw.get("payload")}, sort_keys=True).encode()
            ).hexdigest()[:56]
            transport.ingest(
                worker_id,
                worker_token,
                event_type=ev.event_type,
                source=adapter.normalized_event_sources()[0],
                idempotency_key=f"mqtt:{adapter_cfg.adapter_id}:{h}",
                payload=ev.payload,
            )

    proc = AdapterProcessConfig(
        worker_id=worker_id,
        worker_token=worker_token,
        event_source=adapter.normalized_event_sources()[0],
        heartbeat_interval_seconds=float(os.environ.get("GOLIATH_ADAPTER_HEARTBEAT_SECONDS", "0") or 0),
    )

    run_adapter_process(adapter, transport, cfg=proc, blocking_fn=lambda: adapter.iter_forever(on_message_dict=handle_raw))
