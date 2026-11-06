"""Unit tests for device adapter foundation (no live brokers required)."""

from __future__ import annotations

import unittest

from goliath_app.device_adapter.contract import AdapterCapability
from goliath_app.device_adapter.ha_adapter import HomeAssistantAdapterConfig, HomeAssistantDeviceAdapter
from goliath_app.device_adapter.mqtt_adapter import MqttAdapterConfig, MqttDeviceAdapter
from goliath_app.device_adapter.secrets import SecretRef
from rest.auth import classify_route, RouteTier


class DeviceAdapterRouteTests(unittest.TestCase):
    def test_events_post_is_worker_tier(self) -> None:
        self.assertEqual(classify_route("POST", "/v1/events"), RouteTier.WORKER)


class SecretRefTests(unittest.TestCase):
    def test_resolve_from_env(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"TEST_SECRET_X": "abc123"}):
            ref = SecretRef(env_name="TEST_SECRET_X")
            self.assertEqual(ref.resolve(), "abc123")


class MqttAdapterTranslationTests(unittest.TestCase):
    def test_json_payload_maps_to_event(self) -> None:
        cfg = MqttAdapterConfig(adapter_id="t1", organization_key="org-a", device_key="dev-1")
        adapter = MqttDeviceAdapter(cfg)
        raw = {"topic": "sensors/t", "payload": b'{"temp": 21.5}', "qos": 1, "retain": False}
        evs = list(adapter.translate_to_events(raw))
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].event_type, "device.mqtt.message.v1")
        self.assertEqual(evs[0].payload.get("topic"), "sensors/t")
        self.assertEqual(evs[0].payload.get("payload", {}).get("temp"), 21.5)

    def test_command_topic_glob(self) -> None:
        self.assertTrue(MqttDeviceAdapter.command_publish_topic_allowed("cmd/x", ("cmd/#",)))
        self.assertFalse(MqttDeviceAdapter.command_publish_topic_allowed("other/x", ("cmd/#",)))


class HomeAssistantAdapterTranslationTests(unittest.TestCase):
    def test_state_changed_allowlist(self) -> None:
        cfg = HomeAssistantAdapterConfig(
            adapter_id="ha1",
            organization_key="org-a",
            device_key="site-1",
            base_url="http://127.0.0.1:8123",
            token_ref=SecretRef(env_name="HA_TOKEN_UNUSED"),
            entity_allowlist=("sensor.ok",),
        )
        adapter = HomeAssistantDeviceAdapter(cfg)
        msg = {
            "event": {
                "event_type": "state_changed",
                "data": {
                    "entity_id": "sensor.ok",
                    "new_state": {
                        "state": "42",
                        "last_updated": "2025-01-01T00:00:00+00:00",
                        "attributes": {},
                    },
                },
            }
        }
        evs = list(adapter.translate_to_events(msg))
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].event_type, "device.homeassistant.state_changed.v1")

    def test_empty_allowlist_drops(self) -> None:
        cfg = HomeAssistantAdapterConfig(
            adapter_id="ha2",
            base_url="http://127.0.0.1:8123",
            token_ref=SecretRef(env_name="HA_TOKEN_UNUSED"),
            entity_allowlist=(),
        )
        adapter = HomeAssistantDeviceAdapter(cfg)
        msg = {
            "event": {
                "event_type": "state_changed",
                "data": {"entity_id": "sensor.x", "new_state": {"state": "on"}},
            }
        }
        self.assertEqual(list(adapter.translate_to_events(msg)), [])


class AdapterCapabilityEnumTests(unittest.TestCase):
    def test_enumerate(self) -> None:
        names = {c.value for c in AdapterCapability}
        self.assertIn("telemetry.ingest", names)


if __name__ == "__main__":
    unittest.main()
