"""Tier-2 product wake extensions (registration stub for downstream products)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from goliath_worker.wake import WorkerWakeMessage

Tier2WakeExtension = Callable[
    [Sequence[WorkerWakeMessage], "WakePublishContext"],
    Sequence[WorkerWakeMessage],
]

_tier2_extensions: list[Tier2WakeExtension] = []


@dataclass(frozen=True)
class WakePublishContext:
    reason: str
    event_id: Optional[int] = None
    workflow_instance_id: Optional[int] = None
    payload: Optional[Mapping[str, Any]] = None


def register_tier2_wake_extension(fn: Tier2WakeExtension) -> None:
    """Register a tier-2 product wake hook (called after tier-1 hint expansion)."""
    _tier2_extensions.append(fn)


def apply_tier2_product_wake_extensions(
    messages: Sequence[WorkerWakeMessage],
    context: WakePublishContext,
) -> list[WorkerWakeMessage]:
    out: list[WorkerWakeMessage] = list(messages)
    for ext in _tier2_extensions:
        out = list(ext(out, context))
    return out


__all__ = [
    "WakePublishContext",
    "apply_tier2_product_wake_extensions",
    "register_tier2_wake_extension",
]
