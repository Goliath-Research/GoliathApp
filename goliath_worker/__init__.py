"""Shared claim/submit client, dual-activation wake stubs, and optional /work helpers."""

from .client import WorkflowRestClient
from .wake import (
    NullWorkerWakePublisher,
    NullWorkerWakeSubscriber,
    WorkerWakeMessage,
    WorkerWakePublisher,
    WorkerWakeSubscriber,
    logical_wake_channel_to_pg_notify,
    pg_notify_to_logical_wake_channel,
)

__all__ = [
    "NullWorkerWakePublisher",
    "NullWorkerWakeSubscriber",
    "PostgresWorkerWakePublisher",
    "WorkerWakeMessage",
    "WorkerWakePublisher",
    "WorkerWakeSubscriber",
    "WorkflowRestClient",
    "logical_wake_channel_to_pg_notify",
    "pg_notify_to_logical_wake_channel",
    "postgres_wake_publisher_enabled",
]


def __getattr__(name: str) -> object:
    if name == "PostgresWorkerWakePublisher":
        from . import postgres_wake as _postgres_wake

        return _postgres_wake.PostgresWorkerWakePublisher
    if name == "postgres_wake_publisher_enabled":
        from . import postgres_wake as _postgres_wake

        return _postgres_wake.postgres_wake_publisher_enabled
    if name in (
        "PostgresWorkerWakeSubscriber",
        "resolve_worker_wake_subscriber",
        "resolve_postgres_wake_conninfo",
        "postgres_wake_enabled",
    ):
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}: "
            "worker-side Postgres LISTEN for wakes was removed; use WORKER_WAKE_HTTP=1 "
            "with gateway long-poll (POST /v1/workers/wakes/wait)"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
