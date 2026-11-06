"""ASGI-level tests for the workflow REST gateway."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

import httpx

WF_ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WF_ENGINE))

from rest.asgi import create_app  # noqa: E402
from rest.db.base import GatewayDb, WorkerAuthError, WorkerCallAuth  # noqa: E402
from rest.gateway import RestGateway  # noqa: E402


def _stub_db() -> GatewayDb:
    return cast(GatewayDb, _StubDb())


class _StubDb:
    backend = "postgres"

    def close(self) -> None:
        pass

    def get_worker_cluster_security(self, worker_id: int) -> None:
        return None

    def fetch_worker_wake_hints_for_event(self, event_id: int) -> list[dict[str, object]]:
        _ = event_id
        return []

    def ingest_event_worker(
        self,
        auth: WorkerCallAuth,
        *,
        event_type: str,
        source: str,
        idempotency_key: str,
        payload_json: dict[str, object] | None = None,
        correlation_key: str | None = None,
        occurred_at_utc: str | None = None,
    ) -> dict[str, object]:
        _ = auth, correlation_key, occurred_at_utc
        return {
            "event_id": 99,
            "duplicate": False,
            "applied_count": 0,
            "ignored_count": 1,
        }


class AsgiGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_route(self) -> None:
        app = create_app(RestGateway(_stub_db()))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["backend"], "postgres")

    async def test_worker_auth_error_returns_401(self) -> None:
        gateway = RestGateway(_stub_db())

        def _raise_auth(*args: object, **kwargs: object) -> dict[str, object]:
            raise WorkerAuthError("invalid token")

        with patch("rest.gateway.worker_request_task", side_effect=_raise_auth):
            app = create_app(gateway)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/v1/workers/tasks/request",
                    json={"worker_id": 1},
                    headers={
                        "Authorization": "Bearer session",
                        "X-Goliath-Worker-Token": "identity",
                    },
                )
        self.assertEqual(response.status_code, 401)
        self.assertIn("invalid token", response.json()["error"])

    async def test_events_requires_worker_auth_headers(self) -> None:
        app = create_app(RestGateway(_stub_db()))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/events",
                json={
                    "event_type": "device.test.v1",
                    "source": "pytest",
                    "idempotency_key": "x",
                },
            )
        self.assertEqual(response.status_code, 401)

    async def test_events_dispatches_when_authed(self) -> None:
        app = create_app(RestGateway(_stub_db()))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/events",
                json={
                    "worker_id": 1,
                    "event_type": "device.test.v1",
                    "source": "pytest",
                    "idempotency_key": "key-a",
                    "payload": {"k": "v"},
                },
                headers={
                    "Authorization": "Bearer session",
                    "X-Goliath-Worker-Token": "identity",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["event_id"], 99)


if __name__ == "__main__":
    unittest.main()
