"""Unit tests for dual-activation wake DTOs and gateway hook helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

WF_ENGINE = Path(__file__).resolve().parents[1]
REPO_ROOT = WF_ENGINE.parent
sys.path.insert(0, str(WF_ENGINE))
sys.path.insert(0, str(REPO_ROOT))

from goliath_worker.wake import (  # noqa: E402
    WorkerWakeMessage,
    logical_wake_channel_to_pg_notify,
    wake_channel_for_capability,
    wake_channel_for_pool,
    wake_channel_for_program,
    wake_channels_for_message,
)
from rest.worker_wake import (  # noqa: E402
    publish_wakes_after_event_ingest,
    wake_message_from_event_payload,
)


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, WorkerWakeMessage]] = []

    def publish(self, channel: str, message: WorkerWakeMessage) -> None:
        self.calls.append((channel, message))


class WorkerWakeTests(unittest.TestCase):
    def test_channel_naming_normalizes_segments(self) -> None:
        self.assertEqual(
            wake_channel_for_pool("omics west"),
            "goliath.wake.v1.pool.omics_west",
        )
        self.assertEqual(
            logical_wake_channel_to_pg_notify("goliath.wake.v1.pool.omics_west"),
            "gw1_pool_omics_west",
        )
        self.assertEqual(
            wake_channel_for_capability("align/bam"),
            "goliath.wake.v1.capability.align_bam",
        )
        self.assertEqual(
            wake_channel_for_program("program.v2"),
            "goliath.wake.v1.program.program.v2",
        )

    def test_wake_message_round_trip_json(self) -> None:
        msg = WorkerWakeMessage(
            wake_id="w1",
            reason="test",
            capability="run",
            event_id=42,
        )
        restored = WorkerWakeMessage.from_json(msg.to_json())
        self.assertEqual(restored.wake_id, "w1")
        self.assertEqual(restored.capability, "run")
        self.assertEqual(restored.event_id, 42)

    def test_wake_channels_deduplicate(self) -> None:
        msg = WorkerWakeMessage(
            wake_id="w1",
            reason="test",
            pool="p1",
            capability="c1",
        )
        channels = wake_channels_for_message(msg)
        self.assertEqual(len(channels), 2)
        self.assertEqual(channels[0], wake_channel_for_pool("p1"))
        self.assertEqual(channels[1], wake_channel_for_capability("c1"))

    def test_wake_from_event_payload_optional(self) -> None:
        self.assertIsNone(
            wake_message_from_event_payload({}, reason="r", wake_id="id"),
        )
        msg = wake_message_from_event_payload(
            {"worker_wake": {"capability": "align"}},
            reason="event_ingest:x",
            wake_id="k",
            event_id=7,
        )
        self.assertIsNotNone(msg)
        assert msg is not None
        self.assertEqual(msg.capability, "align")
        self.assertEqual(msg.event_id, 7)

    def test_publish_skips_duplicate_or_no_applied(self) -> None:
        pub = _RecordingPublisher()
        payload = {"worker_wake": {"pool": "p1"}}
        self.assertEqual(
            publish_wakes_after_event_ingest(
                pub,
                ingest_result={"duplicate": True, "applied_count": 1, "event_id": 1},
                event_type="t",
                idempotency_key="k",
                payload=payload,
            ),
            0,
        )
        self.assertEqual(
            publish_wakes_after_event_ingest(
                pub,
                ingest_result={"duplicate": False, "applied_count": 0, "event_id": 1},
                event_type="t",
                idempotency_key="k",
                payload=payload,
            ),
            0,
        )
        self.assertEqual(len(pub.calls), 0)

    def test_publish_on_applied_event(self) -> None:
        pub = _RecordingPublisher()
        count = publish_wakes_after_event_ingest(
            pub,
            ingest_result={"duplicate": False, "applied_count": 2, "event_id": 99},
            event_type="upload.landed",
            idempotency_key="idem-1",
            payload={"worker_wake": {"pool": "west", "program_id": "prog-a"}},
        )
        self.assertEqual(count, 2)
        self.assertEqual(len(pub.calls), 2)
        _, first_msg = pub.calls[0]
        self.assertIn("event:99:idem-1", first_msg.wake_id)
        self.assertEqual(first_msg.reason, "event_ingest:upload.landed")


if __name__ == "__main__":
    unittest.main()
