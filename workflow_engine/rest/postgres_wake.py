"""Gateway Postgres NOTIFY publisher for dual worker activation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from goliath_worker.postgres_wake import PostgresWorkerWakePublisher  # noqa: E402
from goliath_worker.wake import NullWorkerWakePublisher, WorkerWakePublisher  # noqa: E402

from .connection import GatewayConnectionConfig, _env_flag  # noqa: E402
from .wake_coalesce import CoalescingWorkerWakePublisher  # noqa: E402
from .worker_wake_hub import FanOutWorkerWakePublisher, WorkerWakeHub  # noqa: E402


def resolve_wake_publisher(
    config: GatewayConnectionConfig,
    *,
    wake_hub: WorkerWakeHub | None = None,
) -> WorkerWakePublisher:
    """Return Postgres NOTIFY publisher when ``WF_WAKE_POSTGRES=1``, else no-op.

    When ``wake_hub`` is set, each publish also fans out to in-process HTTP waiters. Postgres publishes
    are wrapped in :class:`CoalescingWorkerWakePublisher`; pure in-memory fan-out skips coalescing.
    """
    if not _env_flag("WF_WAKE_POSTGRES"):
        inner_pub: WorkerWakePublisher = NullWorkerWakePublisher()
    else:
        inner_pub = PostgresWorkerWakePublisher(
            config.connection_string,
            use_managed_identity=config.use_managed_identity,
        )

    if wake_hub is not None:
        inner_pub = FanOutWorkerWakePublisher(inner_pub, wake_hub)

    if _env_flag("WF_WAKE_POSTGRES"):
        return CoalescingWorkerWakePublisher(inner_pub)
    return inner_pub


def resolve_wake_publisher_from_env(
    *,
    connection_string: Optional[str] = None,
) -> WorkerWakePublisher:
    from .connection import resolve_connection_config

    config = resolve_connection_config(connection_string=connection_string)
    return resolve_wake_publisher(config)


__all__ = [
    "PostgresWorkerWakePublisher",
    "resolve_wake_publisher",
    "resolve_wake_publisher_from_env",
]
