"""Gateway HTTP long-poll worker wake subscriber (no database on the worker)."""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Optional

from urllib.error import HTTPError
from urllib.request import Request

from goliath_worker.wake import NullWorkerWakeSubscriber, WorkerWakeMessage, WorkerWakeSubscriber


def gateway_wake_http_enabled() -> bool:
    raw = os.environ.get("WORKER_WAKE_HTTP", "").strip().lower()
    return raw in ("1", "true", "yes")


def resolve_http_worker_wake_subscriber(
    base_client: Any,
) -> WorkerWakeSubscriber:
    """Return HTTP long-poll subscriber when ``WORKER_WAKE_HTTP=1``, else null."""
    if not gateway_wake_http_enabled():
        return NullWorkerWakeSubscriber()
    return HttpWorkerWakeSubscriber(base_client)


class HttpWorkerWakeSubscriber:
    """Subscribe via ``POST /v1/workers/wakes/wait`` (same session headers as claim)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def subscribe(
        self,
        channels: Iterable[str],
        *,
        session_token: str,
        worker_id: int,
    ) -> None:
        _ = channels
        if not (session_token or "").strip():
            raise ValueError("subscribe requires a non-empty worker session_token")
        if worker_id <= 0:
            raise ValueError("subscribe requires a positive worker_id")

    def unsubscribe(self) -> None:
        pass

    def wait_for_wake(self, *, timeout_seconds: Optional[float] = None) -> Optional[WorkerWakeMessage]:
        payload = {
            "worker_id": self._client.require_worker_id(),
            "timeout_seconds": timeout_seconds
            if timeout_seconds is not None
            else float(os.environ.get("WORKER_WAKE_POLL_SECONDS", "30")),
        }
        program_id = os.environ.get("WORKER_WAKE_PROGRAM_ID", "").strip()
        if program_id:
            payload["program_id"] = program_id
        body = json.dumps(payload).encode("utf-8")
        url = f"{self._client.base_url}/workers/wakes/wait"
        headers = self._client._default_headers()  # noqa: SLF001
        headers["Content-Type"] = "application/json"
        req = Request(url, data=body, headers=headers, method="POST")
        try:
            from urllib.request import urlopen

            with urlopen(req, timeout=self._client.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                data = json.loads(raw)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} /workers/wakes/wait: {detail}") from exc
        wake = data.get("wake")
        if wake is None:
            return None
        if not isinstance(wake, dict):
            return None
        return WorkerWakeMessage.from_json(wake)
