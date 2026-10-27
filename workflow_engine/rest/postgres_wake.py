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


def resolve_wake_publisher(
    config: GatewayConnectionConfig,
) -> WorkerWakePublisher:
    """Return Postgres NOTIFY publisher when ``WF_WAKE_POSTGRES=1``, else no-op."""
    if not _env_flag("WF_WAKE_POSTGRES"):
        return NullWorkerWakePublisher()
    return PostgresWorkerWakePublisher(
        config.connection_string,
        use_managed_identity=config.use_managed_identity,
    )


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
