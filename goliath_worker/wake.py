"""Dual worker activation: wake notify DTOs and pluggable pub/sub interfaces.

Workers still **claim** via POST /v1/workers/tasks/request after a wake.
This module defines the wake message shape and channel naming only; no broker.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Protocol, runtime_checkable

WAKE_CHANNEL_PREFIX = "goliath.wake.v1"
"""Postgres NOTIFY channel prefix (logical names use dots; NOTIFY identifiers do not)."""
PG_NOTIFY_CHANNEL_PREFIX = "gw1_"
PG_NOTIFY_CHANNEL_MAX_LEN = 63
_SEGMENT_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def _normalize_segment(value: str) -> str:
    cleaned = _SEGMENT_SAFE.sub("_", value.strip())
    if not cleaned:
        raise ValueError("channel segment must not be empty after normalization")
    return cleaned


def wake_channel_for_pool(pool: str) -> str:
    """Channel for workers enrolled in a fleet pool (cluster / worker pool key)."""
    return f"{WAKE_CHANNEL_PREFIX}.pool.{_normalize_segment(pool)}"


def wake_channel_for_capability(capability: str) -> str:
    """Channel for workers that advertise a given capability name."""
    return f"{WAKE_CHANNEL_PREFIX}.capability.{_normalize_segment(capability)}"


def wake_channel_for_program(program_id: str) -> str:
    """Channel for workers bound to a domain program (tier-2 products may narrow further)."""
    return f"{WAKE_CHANNEL_PREFIX}.program.{_normalize_segment(program_id)}"


def logical_wake_channel_to_pg_notify(logical_channel: str) -> str:
    """Map a logical wake channel to a Postgres ``NOTIFY`` identifier (≤63 chars).

    Mapping (see ``docs/dual-activation.md``):

    - Logical: ``goliath.wake.v1.{pool|capability|program}.{segment}``
    - NOTIFY: ``gw1_{pool|capability|program}_{segment}`` (dots → underscores in the prefix path)

    When the NOTIFY name would exceed 63 characters, the segment is replaced with
    ``h`` + the first 16 hex chars of SHA-256(logical_channel).
    """
    prefix = f"{WAKE_CHANNEL_PREFIX}."
    if not logical_channel.startswith(prefix):
        raise ValueError(f"logical wake channel must start with {prefix!r}")
    suffix = logical_channel[len(prefix) :]
    notify = PG_NOTIFY_CHANNEL_PREFIX + suffix.replace(".", "_")
    if len(notify) <= PG_NOTIFY_CHANNEL_MAX_LEN:
        return notify
    digest = hashlib.sha256(logical_channel.encode("utf-8")).hexdigest()[:16]
    # Keep kind (first segment) for observability: gw1_pool_h<digest>
    kind, _, _rest = suffix.partition(".")
    hashed = f"{PG_NOTIFY_CHANNEL_PREFIX}{kind.replace('.', '_')}_h{digest}"
    return hashed[:PG_NOTIFY_CHANNEL_MAX_LEN]


def pg_notify_to_logical_wake_channel(notify_channel: str) -> Optional[str]:
    """Best-effort inverse of :func:`logical_wake_channel_to_pg_notify` (non-hashed names only)."""
    if not notify_channel.startswith(PG_NOTIFY_CHANNEL_PREFIX):
        return None
    body = notify_channel[len(PG_NOTIFY_CHANNEL_PREFIX) :]
    if "_h" in body:
        return None
    kind, _, segment = body.partition("_")
    if kind not in ("pool", "capability", "program") or not segment:
        return None
    return f"{WAKE_CHANNEL_PREFIX}.{kind}.{segment}"


def wake_channels_for_message(message: WorkerWakeMessage) -> list[str]:
    """Return deduplicated channel names implied by a wake message."""
    channels: list[str] = []
    if message.pool:
        channels.append(wake_channel_for_pool(message.pool))
    if message.capability:
        channels.append(wake_channel_for_capability(message.capability))
    if message.program_id:
        channels.append(wake_channel_for_program(message.program_id))
    if not channels:
        raise ValueError("wake message must set at least one of pool, capability, or program_id")
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    out: list[str] = []
    for ch in channels:
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


@dataclass(frozen=True)
class WorkerWakeMessage:
    """Small notify payload; does not transfer task input or lease ownership."""

    wake_id: str
    reason: str
    pool: Optional[str] = None
    capability: Optional[str] = None
    program_id: Optional[str] = None
    event_id: Optional[int] = None
    workflow_instance_id: Optional[int] = None
    occurred_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )

    def to_json(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "wake_id": self.wake_id,
            "reason": self.reason,
            "occurred_at_utc": self.occurred_at_utc,
        }
        if self.pool is not None:
            body["pool"] = self.pool
        if self.capability is not None:
            body["capability"] = self.capability
        if self.program_id is not None:
            body["program_id"] = self.program_id
        if self.event_id is not None:
            body["event_id"] = self.event_id
        if self.workflow_instance_id is not None:
            body["workflow_instance_id"] = self.workflow_instance_id
        return body

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> WorkerWakeMessage:
        return cls(
            wake_id=str(data["wake_id"]),
            reason=str(data["reason"]),
            pool=str(data["pool"]) if data.get("pool") not in (None, "") else None,
            capability=str(data["capability"]) if data.get("capability") not in (None, "") else None,
            program_id=str(data["program_id"]) if data.get("program_id") not in (None, "") else None,
            event_id=int(data["event_id"]) if data.get("event_id") is not None else None,
            workflow_instance_id=(
                int(data["workflow_instance_id"])
                if data.get("workflow_instance_id") is not None
                else None
            ),
            occurred_at_utc=str(data["occurred_at_utc"])
            if data.get("occurred_at_utc")
            else datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )


@runtime_checkable
class WorkerWakePublisher(Protocol):
    """Gateway-side notify hook (Redis, NATS, in-process bus, etc.)."""

    def publish(self, channel: str, message: WorkerWakeMessage) -> None:
        """Deliver one wake to subscribers on ``channel``."""


@runtime_checkable
class WorkerWakeSubscriber(Protocol):
    """Worker-side idle interrupt; implementation requires an authenticated session."""

    def subscribe(
        self,
        channels: Iterable[str],
        *,
        session_token: str,
        worker_id: int,
    ) -> None:
        """Subscribe while idle; ``session_token`` is the gateway worker bearer session."""

    def unsubscribe(self) -> None:
        """Stop listening (before claim loop or on shutdown)."""

    def wait_for_wake(self, *, timeout_seconds: Optional[float] = None) -> Optional[WorkerWakeMessage]:
        """Block until a wake arrives or timeout; ``None`` means poll-only fallback."""


class NullWorkerWakePublisher:
    """Default gateway publisher: no external bus (claim poll remains the fast path)."""

    def publish(self, channel: str, message: WorkerWakeMessage) -> None:
        _ = channel
        _ = message


class NullWorkerWakeSubscriber:
    """Worker stub: never receives wakes; use timed claim poll only."""

    def subscribe(
        self,
        channels: Iterable[str],
        *,
        session_token: str,
        worker_id: int,
    ) -> None:
        _ = channels
        _ = session_token
        _ = worker_id

    def unsubscribe(self) -> None:
        pass

    def wait_for_wake(self, *, timeout_seconds: Optional[float] = None) -> Optional[WorkerWakeMessage]:
        _ = timeout_seconds
        return None
