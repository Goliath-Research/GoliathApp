"""Gateway hook points for dual worker activation (notify via pub/sub, own via claim).

See docs/dual-activation.md. Production brokers are out of scope for the first slice;
``RestGateway`` accepts a ``WorkerWakePublisher`` and defaults to ``NullWorkerWakePublisher``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from goliath_worker.wake import (  # noqa: E402
    NullWorkerWakePublisher,
    WorkerWakeMessage,
    WorkerWakePublisher,
    wake_channels_for_message,
)

from .worker_wake_tier2 import WakePublishContext, apply_tier2_product_wake_extensions  # noqa: E402

WAKE_PAYLOAD_KEY = "worker_wake"

_bound_publisher: Optional[WorkerWakePublisher] = None


def bind_worker_wake_publisher(publisher: Optional[WorkerWakePublisher]) -> None:
    """Bind the gateway wake publisher for DB-layer hooks (instance start, reclaim)."""
    global _bound_publisher
    _bound_publisher = publisher


def _resolve_publisher(explicit: WorkerWakePublisher) -> WorkerWakePublisher:
    if explicit is not None and not isinstance(explicit, NullWorkerWakePublisher):
        return explicit
    if _bound_publisher is not None:
        return _bound_publisher
    return explicit or NullWorkerWakePublisher()


@dataclass(frozen=True)
class WorkerWakeHint:
    pool: Optional[str] = None
    capability: Optional[str] = None
    program_id: Optional[str] = None
    workflow_instance_id: Optional[int] = None


@runtime_checkable
class WorkerWakeHintSource(Protocol):
    def fetch_worker_wake_hints_for_event(self, event_id: int) -> list[WorkerWakeHint]: ...

    def fetch_worker_wake_hints_for_instances(
        self, instance_ids: list[int]
    ) -> list[WorkerWakeHint]: ...

    def fetch_worker_wake_hints_for_node_executions(
        self, node_execution_ids: list[int]
    ) -> list[WorkerWakeHint]: ...


def wake_message_from_event_payload(
    payload: Mapping[str, Any],
    *,
    reason: str,
    wake_id: str,
    event_id: Optional[int] = None,
) -> Optional[WorkerWakeMessage]:
    """Build a wake from optional ``worker_wake`` hints on an ingested event payload."""
    hints = payload.get(WAKE_PAYLOAD_KEY)
    if hints is None:
        return None
    if not isinstance(hints, dict):
        raise ValueError(f"{WAKE_PAYLOAD_KEY} must be a JSON object")
    pool = hints.get("pool")
    capability = hints.get("capability")
    program_id = hints.get("program_id")
    if not any(v not in (None, "") for v in (pool, capability, program_id)):
        return None
    return WorkerWakeMessage(
        wake_id=wake_id,
        reason=reason,
        pool=str(pool) if pool not in (None, "") else None,
        capability=str(capability) if capability not in (None, "") else None,
        program_id=str(program_id) if program_id not in (None, "") else None,
        event_id=event_id,
        workflow_instance_id=(
            int(hints["workflow_instance_id"])
            if hints.get("workflow_instance_id") is not None
            else None
        ),
    )


def _hint_key(hint: WorkerWakeHint) -> tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
    return (hint.pool, hint.capability, hint.program_id, hint.workflow_instance_id)


def _merge_override(
    hints: list[WorkerWakeHint],
    override: Optional[WorkerWakeMessage],
) -> list[WorkerWakeHint]:
    if override is None:
        return hints
    merged: list[WorkerWakeHint] = []
    seen: set[tuple[Optional[str], Optional[str], Optional[str], Optional[int]]] = set()
    override_hint = WorkerWakeHint(
        pool=override.pool,
        capability=override.capability,
        program_id=override.program_id,
        workflow_instance_id=override.workflow_instance_id,
    )
    for item in [override_hint, *hints]:
        key = _hint_key(item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _messages_from_hints(
    hints: list[WorkerWakeHint],
    *,
    reason: str,
    wake_id_prefix: str,
    event_id: Optional[int] = None,
) -> list[WorkerWakeMessage]:
    messages: list[WorkerWakeMessage] = []
    for idx, hint in enumerate(hints):
        if not any(
            v not in (None, "")
            for v in (hint.pool, hint.capability, hint.program_id)
        ):
            continue
        messages.append(
            WorkerWakeMessage(
                wake_id=f"{wake_id_prefix}:{idx}",
                reason=reason,
                pool=hint.pool,
                capability=hint.capability,
                program_id=hint.program_id,
                event_id=event_id,
                workflow_instance_id=hint.workflow_instance_id,
            )
        )
    return messages


def publish_worker_wake_messages(
    publisher: WorkerWakePublisher,
    messages: list[WorkerWakeMessage],
    *,
    context: WakePublishContext,
) -> int:
    """Publish wake messages to all implied channels (after tier-2 extensions)."""
    expanded = apply_tier2_product_wake_extensions(messages, context)
    resolved = _resolve_publisher(publisher)
    count = 0
    for message in expanded:
        for channel in wake_channels_for_message(message):
            resolved.publish(channel, message)
            count += 1
    if hasattr(resolved, "flush"):
        resolved.flush()
    return count


def publish_wakes_after_event_ingest(
    publisher: WorkerWakePublisher,
    db: Any,
    *,
    ingest_result: Mapping[str, Any],
    event_type: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
) -> int:
    """Publish worker wakes after ``POST /v1/events`` when new work may exist."""
    if bool(ingest_result.get("duplicate")):
        return 0
    if int(ingest_result.get("applied_count") or 0) <= 0:
        return 0

    event_id = int(ingest_result["event_id"]) if ingest_result.get("event_id") is not None else None
    wake_id_prefix = f"event:{ingest_result.get('event_id')}:{idempotency_key}"
    reason = f"event_ingest:{event_type}"
    override = wake_message_from_event_payload(
        payload,
        reason=reason,
        wake_id=wake_id_prefix,
        event_id=event_id,
    )

    hints: list[WorkerWakeHint] = []
    if isinstance(db, WorkerWakeHintSource):
        assert event_id is not None
        hints = list(db.fetch_worker_wake_hints_for_event(event_id))

    merged = _merge_override(hints, override)
    messages = _messages_from_hints(
        merged,
        reason=reason,
        wake_id_prefix=wake_id_prefix,
        event_id=event_id,
    )
    if not messages and override is not None:
        messages = [override]

    if not messages:
        return 0

    return publish_worker_wake_messages(
        publisher,
        messages,
        context=WakePublishContext(reason=reason, event_id=event_id, payload=payload),
    )


def publish_wakes_after_workflow_instance_start(
    db: Any,
    instance_id: int,
    *,
    publisher: Optional[WorkerWakePublisher] = None,
) -> int:
    """Publish wakes after ``sp_start_workflow_instance`` (portal/API-started runs)."""
    if not isinstance(db, WorkerWakeHintSource):
        return 0
    hints = db.fetch_worker_wake_hints_for_instances([instance_id])
    wake_id_prefix = f"instance_start:{instance_id}"
    reason = "workflow_instance_start"
    messages = _messages_from_hints(
        hints,
        reason=reason,
        wake_id_prefix=wake_id_prefix,
    )
    if not messages:
        return 0
    pub = _resolve_publisher(publisher or NullWorkerWakePublisher())
    return publish_worker_wake_messages(
        pub,
        messages,
        context=WakePublishContext(reason=reason, workflow_instance_id=instance_id),
    )


def publish_wakes_after_lease_reclaim(
    db: Any,
    node_execution_ids: list[int],
    *,
    publisher: Optional[WorkerWakePublisher] = None,
) -> int:
    """Publish wakes when nodes return to READY after lease reclaim (non-quiet reclaim)."""
    if not node_execution_ids or not isinstance(db, WorkerWakeHintSource):
        return 0
    hints = db.fetch_worker_wake_hints_for_node_executions(node_execution_ids)
    wake_id_prefix = f"reclaim:{node_execution_ids[0]}"
    reason = "lease_reclaim"
    messages = _messages_from_hints(
        hints,
        reason=reason,
        wake_id_prefix=wake_id_prefix,
    )
    if not messages:
        return 0
    pub = _resolve_publisher(publisher or NullWorkerWakePublisher())
    return publish_worker_wake_messages(
        pub,
        messages,
        context=WakePublishContext(reason=reason),
    )


__all__ = [
    "NullWorkerWakePublisher",
    "WAKE_PAYLOAD_KEY",
    "WorkerWakeHint",
    "WorkerWakeHintSource",
    "WorkerWakePublisher",
    "bind_worker_wake_publisher",
    "publish_wakes_after_event_ingest",
    "publish_wakes_after_lease_reclaim",
    "publish_wakes_after_workflow_instance_start",
    "publish_worker_wake_messages",
    "wake_message_from_event_payload",
]
