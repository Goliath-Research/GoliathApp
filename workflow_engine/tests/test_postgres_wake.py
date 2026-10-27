"""Postgres wake broker mapping, publisher notify SQL, and idle-loop integration."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Optional
from unittest import mock

WF_ENGINE = Path(__file__).resolve().parents[1]
REPO_ROOT = WF_ENGINE.parent
sys.path.insert(0, str(WF_ENGINE))
sys.path.insert(0, str(REPO_ROOT))

from goliath_worker.client import TaskPollResult, WorkflowRestClient  # noqa: E402
from goliath_worker.postgres_wake import (  # noqa: E402
    PostgresWorkerWakePublisher,
    PostgresWorkerWakeSubscriber,
)
from goliath_worker.wake import (  # noqa: E402
    WorkerWakeMessage,
    logical_wake_channel_to_pg_notify,
    pg_notify_to_logical_wake_channel,
    wake_channel_for_pool,
)
from rest.postgres_wake import resolve_wake_publisher  # noqa: E402
from rest.connection import GatewayConnectionConfig  # noqa: E402


class PostgresWakeMappingTests(unittest.TestCase):
    def test_logical_to_notify_strips_dots(self) -> None:
        logical = wake_channel_for_pool("omics-west")
        self.assertEqual(logical_wake_channel_to_pg_notify(logical), "gw1_pool_omics-west")

    def test_notify_inverse_simple(self) -> None:
        notify = "gw1_capability_align_bam"
        self.assertEqual(
            pg_notify_to_logical_wake_channel(notify),
            "goliath.wake.v1.capability.align_bam",
        )

    def test_long_logical_channel_is_hashed(self) -> None:
        segment = "x" * 80
        logical = f"goliath.wake.v1.program.{segment}"
        notify = logical_wake_channel_to_pg_notify(logical)
        self.assertLessEqual(len(notify), 63)
        self.assertIn("_h", notify)


class PostgresWakePublisherTests(unittest.TestCase):
    def test_publish_uses_pg_notify_with_mapped_channel(self) -> None:
        pub = PostgresWorkerWakePublisher("postgresql://localhost/test")
        msg = WorkerWakeMessage(wake_id="w1", reason="r", pool="p1")
        logical = wake_channel_for_pool("p1")
        captured: dict[str, Any] = {}

        class FakeCursor:
            def __enter__(self) -> FakeCursor:
                return self

            def __exit__(self, *args: object) -> None:
                pass

            def execute(self, sql: str, params: tuple[str, str]) -> None:
                captured["sql"] = sql
                captured["params"] = params

        fake_conn = mock.Mock()
        fake_conn.closed = False
        fake_conn.cursor.return_value = FakeCursor()

        with mock.patch.object(pub, "_ensure_connection", return_value=fake_conn):
            pub.publish(logical, msg)

        self.assertEqual(captured["params"][0], logical_wake_channel_to_pg_notify(logical))
        payload = json.loads(captured["params"][1])
        self.assertEqual(payload["wake_id"], "w1")
        self.assertEqual(payload["pool"], "p1")


class PostgresWakeSubscriberTests(unittest.TestCase):
    def test_subscribe_requires_session(self) -> None:
        sub = PostgresWorkerWakeSubscriber("postgresql://localhost/test")
        with self.assertRaises(ValueError):
            sub.subscribe([], session_token="", worker_id=1)
        with self.assertRaises(ValueError):
            sub.subscribe([], session_token="tok", worker_id=0)


class _RecordingSubscriber:
    def __init__(self, *, wake: Optional[WorkerWakeMessage] = None) -> None:
        self.wake = wake
        self.subscribe_calls = 0
        self.unsubscribe_calls = 0
        self.wait_calls = 0

    def subscribe(
        self,
        channels: Any,
        *,
        session_token: str,
        worker_id: int,
    ) -> None:
        self.subscribe_calls += 1

    def unsubscribe(self) -> None:
        self.unsubscribe_calls += 1

    def wait_for_wake(self, *, timeout_seconds: Optional[float] = None) -> Optional[WorkerWakeMessage]:
        self.wait_calls += 1
        return self.wake


class IdleClaimIntegrationTests(unittest.TestCase):
    def test_wait_idle_then_request_task_always_claims(self) -> None:
        client = WorkflowRestClient(base_url="http://example.invalid/v1")
        client._worker_id = 7
        client._session_token = "session"
        client._identity_token = "identity"
        sub = _RecordingSubscriber(wake=WorkerWakeMessage(wake_id="w", reason="r", pool="p"))

        claim_calls: list[dict[str, Any]] = []

        def fake_request_task(**kwargs: Any) -> TaskPollResult:
            claim_calls.append(kwargs)
            return TaskPollResult(claim=None)

        with mock.patch.object(client, "request_task", side_effect=fake_request_task):
            result = client.wait_idle_then_request_task(
                sub,
                ["goliath.wake.v1.pool.p"],
                poll_timeout_seconds=1.0,
            )

        self.assertIsNone(result.claim)
        self.assertEqual(sub.subscribe_calls, 1)
        self.assertEqual(sub.wait_calls, 1)
        self.assertEqual(sub.unsubscribe_calls, 1)
        self.assertEqual(len(claim_calls), 1)


class ResolveWakePublisherTests(unittest.TestCase):
    def test_default_null_publisher(self) -> None:
        config = GatewayConnectionConfig(
            schema_name="wf",
            connection_string="postgresql://localhost/x",
        )
        with mock.patch.dict("os.environ", {}, clear=True):
            pub = resolve_wake_publisher(config)
        self.assertEqual(type(pub).__name__, "NullWorkerWakePublisher")

    def test_postgres_when_flag_set(self) -> None:
        config = GatewayConnectionConfig(
            schema_name="wf",
            connection_string="postgresql://localhost/x",
        )
        with mock.patch.dict("os.environ", {"WF_WAKE_POSTGRES": "1"}):
            pub = resolve_wake_publisher(config)
        self.assertIsInstance(pub, PostgresWorkerWakePublisher)


if __name__ == "__main__":
    unittest.main()
