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
    "PostgresWorkerWakeSubscriber",
    "WorkerWakeMessage",
    "WorkerWakePublisher",
    "WorkerWakeSubscriber",
    "WorkflowRestClient",
    "logical_wake_channel_to_pg_notify",
    "pg_notify_to_logical_wake_channel",
    "postgres_wake_enabled",
    "resolve_postgres_wake_conninfo",
    "resolve_worker_wake_subscriber",
]


def __getattr__(name: str) -> object:
    if name in (
        "PostgresWorkerWakePublisher",
        "PostgresWorkerWakeSubscriber",
        "postgres_wake_enabled",
        "resolve_postgres_wake_conninfo",
        "resolve_worker_wake_subscriber",
    ):
        from . import postgres_wake as _postgres_wake

        return getattr(_postgres_wake, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
