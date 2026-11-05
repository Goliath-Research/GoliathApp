"""Tests for automatic worker wake publishing, coalescing, and dual-claim behavior."""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from typing import Any, Optional, Sequence
from unittest import mock

WF_ENGINE = Path(__file__).resolve().parents[1]
REPO_ROOT = WF_ENGINE.parent
sys.path.insert(0, str(WF_ENGINE))
sys.path.insert(0, str(REPO_ROOT))

from goliath_worker.wake import (  # noqa: E402
    NullWorkerWakeSubscriber,
    WorkerWakeMessage,
    wake_channel_for_capability,
)
from goliath_worker.client import TaskClaim, TaskPollResult, WorkflowRestClient  # noqa: E402
from rest.wake_coalesce import CoalescingWorkerWakePublisher, _truncate_payload  # noqa: E402
from rest.worker_wake import (  # noqa: E402
    WorkerWakeHint,
    publish_wakes_after_event_ingest,
    publish_worker_wake_messages,
)
from rest.worker_wake_tier2 import WakePublishContext, register_tier2_wake_extension  # noqa: E402


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, WorkerWakeMessage]] = []
        self._lock = threading.Lock()

    def publish(self, channel: str, message: WorkerWakeMessage) -> None:
        with self._lock:
            self.calls.append((channel, message))


class _HintDb:
    def fetch_worker_wake_hints_for_event(self, event_id: int) -> list[WorkerWakeHint]:
        _ = event_id
        return [
            WorkerWakeHint(capability="align", workflow_instance_id=10),
        ]

    def fetch_worker_wake_hints_for_instances(self, instance_ids: list[int]) -> list[WorkerWakeHint]:
        return [WorkerWakeHint(capability="run", workflow_instance_id=instance_ids[0])]

    def fetch_worker_wake_hints_for_node_executions(
        self, node_execution_ids: list[int]
    ) -> list[WorkerWakeHint]:
        _ = node_execution_ids
        return []


class AutoWakePublishTests(unittest.TestCase):
    def test_event_ingest_publishes_subscription_derived_hints_without_payload_override(self) -> None:
        pub = _RecordingPublisher()
        count = publish_wakes_after_event_ingest(
            pub,
            _HintDb(),
            ingest_result={"duplicate": False, "applied_count": 1, "event_id": 5},
            event_type="work.ready",
            idempotency_key="k1",
            payload={},
        )
        self.assertEqual(count, 1)
        self.assertEqual(len(pub.calls), 1)
        channel, msg = pub.calls[0]
        self.assertEqual(channel, wake_channel_for_capability("align"))
        self.assertEqual(msg.capability, "align")

    def test_payload_worker_wake_overrides_auto_hints(self) -> None:
        pub = _RecordingPublisher()
        publish_wakes_after_event_ingest(
            pub,
            _HintDb(),
            ingest_result={"duplicate": False, "applied_count": 1, "event_id": 6},
            event_type="t",
            idempotency_key="k2",
            payload={"worker_wake": {"pool": "west"}},
        )
        pools = [ch for ch, _ in pub.calls if ".pool." in ch]
        self.assertTrue(pools)

    def test_coalescing_publisher_batches_burst(self) -> None:
        inner = _RecordingPublisher()
        coalesced = CoalescingWorkerWakePublisher(inner, debounce_seconds=0.08)
        msg = WorkerWakeMessage(wake_id="w", reason="r", capability="c1")
        channel = wake_channel_for_capability("c1")
        for _ in range(5):
            coalesced.publish(channel, msg)
        self.assertEqual(len(inner.calls), 0)
        flushed = coalesced.flush()
        self.assertEqual(flushed, 1)
        self.assertEqual(len(inner.calls), 1)

    def test_notify_payload_stays_under_limit(self) -> None:
        huge = "x" * 9000
        msg = WorkerWakeMessage(wake_id=huge, reason="r", capability="c")
        payload = _truncate_payload(msg)
        self.assertLessEqual(len(payload.encode("utf-8")), 8000)

    def test_tier2_extension_hook_runs(self) -> None:
        pub = _RecordingPublisher()

        def _ext(
            messages: Sequence[WorkerWakeMessage], _ctx: WakePublishContext
        ) -> Sequence[WorkerWakeMessage]:
            if not messages:
                return messages
            first = messages[0]
            return [
                WorkerWakeMessage(
                    wake_id=first.wake_id + ":tier2",
                    reason=first.reason,
                    capability=first.capability,
                )
            ]

        register_tier2_wake_extension(_ext)
        try:
            publish_worker_wake_messages(
                pub,
                [WorkerWakeMessage(wake_id="w0", reason="r", capability="cap-a")],
                context=WakePublishContext(reason="r"),
            )
            self.assertTrue(any("tier2" in m.wake_id for _, m in pub.calls))
        finally:
            from rest import worker_wake_tier2 as tier2_mod

            tier2_mod._tier2_extensions.pop()


class DualWorkerClaimTests(unittest.TestCase):
    def test_two_workers_wake_then_single_claim_winner(self) -> None:
        wake_msg = WorkerWakeMessage(wake_id="w", reason="r", capability="task-cap")
        claimed: list[int] = []
        claim_lock = threading.Lock()

        def make_client(worker_num: int) -> WorkflowRestClient:
            client = WorkflowRestClient(base_url="http://example.invalid/v1")
            client._worker_id = worker_num
            client._session_token = f"sess-{worker_num}"
            client._identity_token = f"id-{worker_num}"
            return client

        class _WakeSub:
            def subscribe(self, *args: Any, **kwargs: Any) -> None:
                pass

            def unsubscribe(self) -> None:
                pass

            def wait_for_wake(self, *, timeout_seconds: Optional[float] = None) -> WorkerWakeMessage:
                _ = timeout_seconds
                return wake_msg

        def fake_request_task(self: WorkflowRestClient, **kwargs: Any) -> TaskPollResult:
            _ = kwargs
            with claim_lock:
                if claimed:
                    return TaskPollResult(claim=None)
                claimed.append(self._worker_id or 0)
                return TaskPollResult(
                    claim=TaskClaim(
                        node_execution_id=1,
                        workflow_instance_id=2,
                        node_key="n",
                        action_name="a",
                        capability="task-cap",
                        attempt_no=1,
                        input_json={},
                        iteration_no=0,
                    )
                )

        w1 = make_client(1)
        w2 = make_client(2)
        channels = [wake_channel_for_capability("task-cap")]

        with mock.patch.object(WorkflowRestClient, "request_task", fake_request_task):
            r1 = w1.wait_idle_then_request_task(_WakeSub(), channels, poll_timeout_seconds=0.01)
            r2 = w2.wait_idle_then_request_task(_WakeSub(), channels, poll_timeout_seconds=0.01)

        self.assertIsNotNone(r1.claim)
        self.assertIsNone(r2.claim)
        self.assertEqual(len(claimed), 1)

    def test_null_subscriber_poll_fallback_without_broker(self) -> None:
        client = WorkflowRestClient(base_url="http://example.invalid/v1")
        client._worker_id = 1
        client._session_token = "s"
        client._identity_token = "i"
        sub = NullWorkerWakeSubscriber()
        with mock.patch.object(
            client,
            "request_task",
            return_value=TaskPollResult(claim=None),
        ) as req:
            client.wait_idle_then_request_task(
                sub,
                [],
                poll_timeout_seconds=0.01,
            )
        req.assert_called_once()


if __name__ == "__main__":
    unittest.main()
