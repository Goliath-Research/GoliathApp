"""Gateway hook points for dual worker activation (notify via pub/sub, own via claim).

See docs/dual-activation.md. Production brokers are out of scope for the first slice;
``RestGateway`` accepts a ``WorkerWakePublisher`` and defaults to ``NullWorkerWakePublisher``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from goliath_worker.wake import (  # noqa: E402
    NullWorkerWakePublisher,
    WorkerWakeMessage,
    WorkerWakePublisher,
    wake_channels_for_message,
)

WAKE_PAYLOAD_KEY = "worker_wake"


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


def publish_wakes_after_event_ingest(
    publisher: WorkerWakePublisher,
    *,
    ingest_result: Mapping[str, Any],
    event_type: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
) -> int:
    """Publish worker wakes after ``POST /v1/events`` when new work may exist.

    Hook points (future PRs may add more):
    - After ``wf.sp_ingest_event`` when ``duplicate`` is false and ``applied_count`` > 0.
    - After portal/instance start edges once those routes call the same helper.

    Returns the number of channel publishes attempted.
    """
    if bool(ingest_result.get("duplicate")):
        return 0
    if int(ingest_result.get("applied_count") or 0) <= 0:
        return 0

    wake_id = f"event:{ingest_result.get('event_id')}:{idempotency_key}"
    message = wake_message_from_event_payload(
        payload,
        reason=f"event_ingest:{event_type}",
        wake_id=wake_id,
        event_id=int(ingest_result["event_id"]) if ingest_result.get("event_id") is not None else None,
    )
    if message is None:
        return 0

    count = 0
    for channel in wake_channels_for_message(message):
        publisher.publish(channel, message)
        count += 1
    return count


__all__ = [
    "NullWorkerWakePublisher",
    "WAKE_PAYLOAD_KEY",
    "WorkerWakePublisher",
    "publish_wakes_after_event_ingest",
    "wake_message_from_event_payload",
]
