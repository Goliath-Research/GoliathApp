"""Gateway-mediated worker wakes (HTTP long-poll; no worker Postgres LISTEN)."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any, cast

WF_ENGINE = Path(__file__).resolve().parents[1]
REPO_ROOT = WF_ENGINE.parent
sys.path.insert(0, str(WF_ENGINE))
sys.path.insert(0, str(REPO_ROOT))

from goliath_worker.wake import WorkerWakeMessage, wake_channel_for_pool  # noqa: E402
from rest.db.base import GatewayDb, WorkerCallAuth  # noqa: E402
from rest.gateway import RestGateway  # noqa: E402
from rest.worker_wake_hub import WorkerWakeHub, WorkerWakeWaitConflict  # noqa: E402


class WorkerWakeHubTests(unittest.TestCase):
    def test_hub_delivers_matching_wake(self) -> None:
        hub = WorkerWakeHub()
        logical = wake_channel_for_pool("west")
        msg = WorkerWakeMessage(wake_id="w1", reason="r", pool="west")
        out: list[WorkerWakeMessage | None] = []

        def waiter() -> None:
            out.append(hub.wait_for_wake(9, frozenset({logical}), timeout_seconds=2.0))

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.02)
        hub.publish_wake(logical, msg)
        t.join(timeout=5.0)
        self.assertFalse(t.is_alive())
        self.assertEqual(len(out), 1)
        self.assertIsNotNone(out[0])
        assert out[0] is not None
        self.assertEqual(out[0].wake_id, "w1")

    def test_hub_concurrent_wait_same_worker_raises(self) -> None:
        hub = WorkerWakeHub()
        logical = wake_channel_for_pool("p")
        msg = WorkerWakeMessage(wake_id="done", reason="r", pool="p")

        def block() -> None:
            hub.wait_for_wake(3, frozenset({logical}), timeout_seconds=10.0)

        t = threading.Thread(target=block)
        t.start()
        time.sleep(0.05)
        with self.assertRaises(WorkerWakeWaitConflict):
            hub.wait_for_wake(3, frozenset({logical}), timeout_seconds=0.05)
        hub.publish_wake(logical, msg)
        t.join(timeout=2.0)
        self.assertFalse(t.is_alive())


class GatewayWorkerWakeWaitTests(unittest.TestCase):
    def test_wait_rejects_missing_worker_auth(self) -> None:
        hub = WorkerWakeHub()
        gw = RestGateway(cast(GatewayDb, _MinimalDb()), wake_hub=hub)
        status, _body = gw.dispatch(
            "POST",
            "/v1/workers/wakes/wait",
            {"worker_id": 1, "timeout_seconds": 1.0},
            client_ip="127.0.0.1",
            worker_auth=None,
        )
        self.assertEqual(status, 401)

    def test_wait_returns_wake_json(self) -> None:
        hub = WorkerWakeHub()
        gw = RestGateway(cast(GatewayDb, _MinimalDb()), wake_hub=hub)
        logical = wake_channel_for_pool("pool-a")
        msg = WorkerWakeMessage(wake_id="e", reason="ingest", pool="pool-a")

        def publisher() -> None:
            time.sleep(0.05)
            hub.publish_wake(logical, msg)

        threading.Thread(target=publisher).start()
        status, body = gw.dispatch(
            "POST",
            "/v1/workers/wakes/wait",
            {"worker_id": 5, "timeout_seconds": 2.0},
            client_ip="127.0.0.1",
            worker_auth=_auth(5),
        )
        self.assertEqual(status, 200)
        assert isinstance(body, dict)
        self.assertFalse(body.get("timed_out"))
        wake = body.get("wake")
        assert isinstance(wake, dict)
        self.assertEqual(wake["wake_id"], "e")

    def test_timeout_returns_null_wake(self) -> None:
        hub = WorkerWakeHub()
        gw = RestGateway(cast(GatewayDb, _MinimalDb()), wake_hub=hub)
        status, body = gw.dispatch(
            "POST",
            "/v1/workers/wakes/wait",
            {"worker_id": 5, "timeout_seconds": 0.05},
            client_ip="127.0.0.1",
            worker_auth=_auth(5),
        )
        self.assertEqual(status, 200)
        assert isinstance(body, dict)
        self.assertTrue(body.get("timed_out"))
        self.assertIsNone(body.get("wake"))


class _MinimalDb:
    backend = "postgres"

    def close(self) -> None:
        pass

    def get_worker_cluster_security(self, worker_id: int) -> None:
        return None

    def worker_resolve_session_for_wake(
        self,
        session_token: str,
        identity_token: str,
        client_ip: str,
    ) -> dict[str, Any]:
        _ = session_token
        _ = identity_token
        _ = client_ip
        return {"worker_id": 5, "cluster_key": "pool-a", "capabilities": ["align"]}


def _auth(worker_id: int) -> WorkerCallAuth:
    return WorkerCallAuth(
        worker_id=worker_id,
        session_token="sess",
        identity_token="ident",
        client_ip="127.0.0.1",
    )


if __name__ == "__main__":
    unittest.main()
