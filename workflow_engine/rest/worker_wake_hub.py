"""In-process wake fan-out from gateway publish to long-polling HTTP workers.

Workers never connect to Postgres for wakes; the gateway LISTEN/NOTIFY or other
publisher delivers to this hub on each logical-channel publish.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from goliath_worker.wake import WorkerWakeMessage, WorkerWakePublisher, wake_channels_for_message

__all__ = [
    "FanOutWorkerWakePublisher",
    "WorkerWakeHub",
    "WorkerWakeWaitConflict",
]


class WorkerWakeWaitConflict(Exception):
    """Another long-poll wait is already active for this worker."""


class _Waiter:
    __slots__ = ("channels", "deadline", "_event", "_message", "_lock")

    def __init__(self, channels: frozenset[str], deadline: float) -> None:
        self.channels = channels
        self.deadline = deadline
        self._event = threading.Event()
        self._message: Optional[WorkerWakeMessage] = None
        self._lock = threading.Lock()

    def try_set_message(self, message: WorkerWakeMessage) -> bool:
        with self._lock:
            if self._message is not None:
                return False
            self._message = message
            self._event.set()
            return True

    def get_message(self) -> Optional[WorkerWakeMessage]:
        with self._lock:
            return self._message

    def wait(self, timeout: float) -> None:
        self._event.wait(timeout=timeout)


class WorkerWakeHub:
    """Match published logical-channel wakes to waiting worker sessions."""

    def __init__(self) -> None:
        self._global = threading.Lock()
        self._waiters: dict[int, _Waiter] = {}

    def wait_for_wake(
        self,
        worker_id: int,
        channels: frozenset[str],
        *,
        timeout_seconds: float,
    ) -> Optional[WorkerWakeMessage]:
        """Block up to timeout_seconds until a wake matches ``channels`` (intersection)."""
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self._global:
            if worker_id in self._waiters:
                raise WorkerWakeWaitConflict("worker already has an active wake wait")
            w = _Waiter(channels, deadline)
            self._waiters[worker_id] = w
        try:
            while True:
                now = time.monotonic()
                remaining = deadline - now
                if remaining <= 0:
                    return None
                msg = w.get_message()
                if msg is not None:
                    return msg
                w.wait(timeout=min(remaining, 1.0))
                msg = w.get_message()
                if msg is not None:
                    return msg
        finally:
            with self._global:
                self._waiters.pop(worker_id, None)

    def publish_wake(self, channel: str, message: WorkerWakeMessage) -> None:
        """Deliver a wake to any registered waiters whose channel set intersects the message."""
        try:
            logical_channels = set(wake_channels_for_message(message))
        except ValueError:
            return
        logical_channels.add(channel)
        with self._global:
            waiters = list(self._waiters.items())
        for _wid, waiter in waiters:
            if waiter.channels & logical_channels:
                waiter.try_set_message(message)


class FanOutWorkerWakePublisher:
    """Forward publishes to an inner gateway publisher and the in-process hub."""

    def __init__(self, inner: WorkerWakePublisher, hub: WorkerWakeHub) -> None:
        self._inner = inner
        self._hub = hub

    def publish(self, channel: str, message: WorkerWakeMessage) -> None:
        self._inner.publish(channel, message)
        self._hub.publish_wake(channel, message)

    def flush(self) -> int:
        if hasattr(self._inner, "flush"):
            return int(self._inner.flush())  # type: ignore[no-any-return]
        return 0

    def close(self) -> None:
        if hasattr(self._inner, "close"):
            self._inner.close()
