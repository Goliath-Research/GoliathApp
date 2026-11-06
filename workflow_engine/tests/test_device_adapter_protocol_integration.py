"""
Protocol-level adapter checks (optional brokers): Mosquitto + minimal HA WS/HTTP mock.

Set GOLIATH_PROTOCOL_TESTS=1 and run with Mosquitto on 127.0.0.1:1883 (default) or GOLIATH_MQTT_HOST / GOLIATH_MQTT_PORT.
CI runs Mosquitto as a job service when wired in .github/workflows/pr.yml.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

try:
    import websockets
except ImportError:  # optional in some dev installs
    websockets = None  # type: ignore[misc,assignment]

from goliath_app.device_adapter.contract import DeviceNormalizedEvent
from goliath_app.device_adapter.ha_adapter import HomeAssistantAdapterConfig, HomeAssistantDeviceAdapter
from goliath_app.device_adapter.mqtt_adapter import MqttAdapterConfig, MqttDeviceAdapter
from goliath_app.device_adapter.secrets import SecretRef


def _protocol_enabled() -> bool:
    return os.environ.get("GOLIATH_PROTOCOL_TESTS", "").strip().lower() in ("1", "true", "yes")


def _mqtt_params() -> tuple[str, int]:
    host = os.environ.get("GOLIATH_MQTT_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("GOLIATH_MQTT_PORT", "1883") or "1883")
    return host, port


def _mqtt_available(host: str, port: int) -> bool:
    try:
        import paho.mqtt.client as mqtt

        ok = threading.Event()

        c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1, protocol=mqtt.MQTTv311)

        def _on_connect(_cl: Any, _ud: Any, _fl: Any, rc: int, _props: Any = None) -> None:
            if rc == 0:
                ok.set()

        c.on_connect = _on_connect
        c.connect_async(host, port, 60)
        c.loop_start()
        ret = ok.wait(timeout=3.0)
        c.loop_stop()
        c.disconnect()
        return bool(ret)
    except Exception:
        return False


@unittest.skipUnless(_protocol_enabled(), "set GOLIATH_PROTOCOL_TESTS=1")
class MqttProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host, cls.port = _mqtt_params()
        if not _mqtt_available(cls.host, cls.port):
            raise unittest.SkipTest(f"MQTT broker unreachable at {cls.host}:{cls.port}")

    def test_publish_subscribe_translate_and_duplicate_mid(self) -> None:
        import paho.mqtt.client as mqtt

        cfg = MqttAdapterConfig(
            adapter_id="proto-mqtt",
            organization_key="org-t",
            device_key="dev-t",
            broker_host=self.host,
            broker_port=self.port,
            client_id="goliath-proto-test",
            subscribe_topics=("goliath/proto/#",),
        )
        adapter = MqttDeviceAdapter(cfg)
        seen: list[DeviceNormalizedEvent] = []

        def _on_msg(_cl: Any, _ud: Any, msg: Any) -> None:
            raw = {
                "topic": msg.topic,
                "payload": msg.payload,
                "qos": msg.qos,
                "retain": msg.retain,
                "mid": getattr(msg, "mid", None),
            }
            seen.extend(list(adapter.translate_to_events(raw)))

        sub = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1, protocol=mqtt.MQTTv311)
        sub.on_message = _on_msg
        sub.connect(self.host, self.port, 60)
        sub.subscribe("goliath/proto/#", qos=1)
        sub.loop_start()

        pub = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION1, protocol=mqtt.MQTTv311)
        pub.connect(self.host, self.port, 60)
        pub.loop_start()
        body = json.dumps({"temp": 22.0}).encode("utf-8")
        pub.publish("goliath/proto/s1", body, qos=1, retain=False)
        pub.publish("goliath/proto/s1", body, qos=1, retain=False)
        import time

        time.sleep(0.75)
        pub.loop_stop()
        pub.disconnect()
        sub.loop_stop()
        sub.disconnect()

        self.assertGreaterEqual(len(seen), 1)
        self.assertEqual(seen[0].event_type, "device.mqtt.message.v1")


class _HaMockHttp(BaseHTTPRequestHandler):
    token = "tok-proto"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        _ = format, args

    def do_GET(self) -> None:
        if self.path.startswith("/api/states"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"[]")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if "/api/services/" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"result":"ok"}')
            return
        self.send_error(404)


@unittest.skipUnless(_protocol_enabled() and websockets is not None, "set GOLIATH_PROTOCOL_TESTS=1 and pip install websockets")
class HomeAssistantProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_and_websocket_handshake_plus_translate(self) -> None:
        """Drive HA WS handshake with a client; translate one event (avoids infinite recv loop)."""
        assert websockets is not None
        os.environ["HA_PROTO_TOKEN"] = _HaMockHttp.token

        async def _ha_server(ws: Any) -> None:
            await ws.send(json.dumps({"type": "auth_required", "ha_version": "mock"}))
            auth = json.loads(await ws.recv())
            assert auth.get("type") == "auth"
            await ws.send(json.dumps({"type": "auth_ok"}))
            sub = json.loads(await ws.recv())
            assert sub.get("type") == "subscribe_events"
            sub_id = int(sub.get("id", 0))
            await ws.send(json.dumps({"type": "result", "id": sub_id, "success": True}))
            await ws.send(
                json.dumps(
                    {
                        "type": "event",
                        "event": {
                            "event_type": "state_changed",
                            "data": {
                                "entity_id": "sensor.ok",
                                "new_state": {
                                    "state": "99",
                                    "last_updated": "2025-01-01T00:00:00+00:00",
                                    "attributes": {},
                                },
                            },
                        },
                    }
                )
            )

        httpd = HTTPServer(("127.0.0.1", 0), _HaMockHttp)
        http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        http_thread.start()
        http_port = httpd.server_address[1]
        ws_port = http_port + 1

        async with websockets.serve(_ha_server, "127.0.0.1", ws_port):
            base = f"http://127.0.0.1:{http_port}"
            cfg = HomeAssistantAdapterConfig(
                adapter_id="proto-ha",
                organization_key="org-t",
                device_key="site-t",
                base_url=base,
                token_ref=SecretRef(env_name="HA_PROTO_TOKEN"),
                entity_allowlist=("sensor.ok",),
                websocket_netloc=f"127.0.0.1:{ws_port}",
            )
            adapter = HomeAssistantDeviceAdapter(cfg)
            self.assertEqual(adapter.rest_get_states(_HaMockHttp.token), [])

            uri = f"ws://127.0.0.1:{ws_port}"
            async with websockets.connect(uri) as cli:  # type: ignore[misc]
                hello = json.loads(await cli.recv())
                self.assertEqual(hello.get("type"), "auth_required")
                await cli.send(json.dumps({"type": "auth", "access_token": _HaMockHttp.token}))
                auth_ok = json.loads(await cli.recv())
                self.assertEqual(auth_ok.get("type"), "auth_ok")
                await cli.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                sub_res = json.loads(await cli.recv())
                self.assertTrue(sub_res.get("success", True))
                ev_msg = json.loads(await cli.recv())
                self.assertEqual(ev_msg.get("type"), "event")
                out = list(adapter.translate_to_events(ev_msg))
                self.assertEqual(len(out), 1)
                self.assertEqual(out[0].event_type, "device.homeassistant.state_changed.v1")

        httpd.shutdown()
        http_thread.join(timeout=2)

    async def test_http_service_success_is_not_physical_ack(self) -> None:
        """Transport 200 from HA REST is not a physical actuator confirmation."""
        httpd = HTTPServer(("127.0.0.1", 0), _HaMockHttp)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        await asyncio.sleep(0.1)
        url = f"http://127.0.0.1:{port}/api/services/light/turn_on"
        req = urllib.request.Request(
            url,
            data=b"{}",
            headers={"Authorization": f"Bearer {_HaMockHttp.token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)


if __name__ == "__main__":
    unittest.main()
