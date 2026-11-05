"""Coalescing wrapper for worker wake publishers (NOTIFY burst control)."""

from __future__ import annotations

import json
import os
import threading
from typing import Optional

from goliath_worker.wake import WorkerWakeMessage, WorkerWakePublisher

PG_NOTIFY_PAYLOAD_MAX_BYTES = 8000


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _truncate_payload(message: WorkerWakeMessage) -> str:
    body = message.to_json()
    payload = json.dumps(body, separators=(",", ":"))
    if len(payload.encode("utf-8")) <= PG_NOTIFY_PAYLOAD_MAX_BYTES:
        return payload
    minimal = {
        "wake_id": body["wake_id"],
        "reason": body["reason"],
        "occurred_at_utc": body["occurred_at_utc"],
    }
    for key in ("pool", "capability", "program_id"):
        if key in body:
            minimal[key] = body[key]
    payload = json.dumps(minimal, separators=(",", ":"))
    if len(payload.encode("utf-8")) <= PG_NOTIFY_PAYLOAD_MAX_BYTES:
        return payload
    minimal_wake = str(body["wake_id"])[:120]
    payload = json.dumps(
        {"wake_id": minimal_wake, "reason": str(body["reason"])[:200]},
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) <= PG_NOTIFY_PAYLOAD_MAX_BYTES:
        return payload
    return json.dumps({"wake_id": minimal_wake[:32], "reason": "wake"}, separators=(",", ":"))


class CoalescingWorkerWakePublisher:
    """Debounces publishes per logical channel; flushes on a short timer."""

    def __init__(
        self,
        inner: WorkerWakePublisher,
        *,
        debounce_seconds: Optional[float] = None,
    ) -> None:
        self._inner = inner
        self._debounce = debounce_seconds
        if self._debounce is None:
            self._debounce = _env_float("WF_WAKE_COALESCE_SECONDS", 0.05)
        self._lock = threading.Lock()
        self._pending: dict[str, WorkerWakeMessage] = {}
        self._timer: Optional[threading.Timer] = None

    @property
    def inner(self) -> WorkerWakePublisher:
        return self._inner

    def publish(self, channel: str, message: WorkerWakeMessage) -> None:
        with self._lock:
            self._pending[channel] = message
            if self._debounce <= 0:
                self._flush_locked()
                return
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> int:
        with self._lock:
            return self._flush_locked()

    def _flush_locked(self) -> int:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if not self._pending:
            return 0
        pending = self._pending
        self._pending = {}
        count = 0
        for channel, message in pending.items():
            _ = _truncate_payload(message)
            self._inner.publish(channel, message)
            count += 1
        return count

    def close(self) -> None:
        self.flush()
        if hasattr(self._inner, "close"):
            self._inner.close()


__all__ = [
    "CoalescingWorkerWakePublisher",
    "PG_NOTIFY_PAYLOAD_MAX_BYTES",
    "_truncate_payload",
]
