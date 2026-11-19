"""Postgres NOTIFY publisher for gateway-side dual worker activation (NOT workers)."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import psycopg

from goliath_worker.platform_env import resolve_database_url_override
from goliath_worker.wake import WorkerWakeMessage, logical_wake_channel_to_pg_notify, pg_notify_payload_json


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in ("1", "true", "yes")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def postgres_wake_publisher_enabled() -> bool:
    """True when the gateway should use Postgres NOTIFY for publishing wakes."""
    return _env_flag("WF_WAKE_POSTGRES")


def build_postgres_conninfo(*, use_managed_identity: bool = False) -> str:
    override = resolve_database_url_override()
    if override:
        return override

    host = _env("PGHOST") or _env("POSTGRES_HOST", "localhost")
    port = _env("PGPORT") or _env("POSTGRES_PORT", "5432")
    db = _env("PGDATABASE") or _env("POSTGRES_DB", "goliath")
    user = quote(_env("PGUSER") or _env("POSTGRES_USER", "postgres"), safe="")
    sslmode = _env("PGSSLMODE", "prefer")
    if use_managed_identity:
        return f"postgresql://{user}@{host}:{port}/{db}?sslmode={sslmode}"
    password = quote(_env("PGPASSWORD") or _env("POSTGRES_PASSWORD"), safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}?sslmode={sslmode}"


def _database_access_token() -> str:
    wf_engine = Path(__file__).resolve().parents[1] / "workflow_engine"
    if str(wf_engine) not in sys.path:
        sys.path.insert(0, str(wf_engine))
    from rest.azure_auth import get_database_access_token

    return get_database_access_token()


def _connect(conninfo: str, *, use_managed_identity: bool = False) -> psycopg.Connection[Any]:
    if use_managed_identity:
        return psycopg.connect(conninfo, password=_database_access_token())
    return psycopg.connect(conninfo)


class PostgresWorkerWakePublisher:
    """Gateway-side ``NOTIFY`` publisher (uses a dedicated connection, not the request pool)."""

    def __init__(
        self,
        conninfo: str,
        *,
        use_managed_identity: bool = False,
    ) -> None:
        self._conninfo = conninfo
        self._use_managed_identity = use_managed_identity
        self._lock = threading.Lock()
        self._conn: Optional[psycopg.Connection[Any]] = None

    def _ensure_connection(self) -> psycopg.Connection[Any]:
        with self._lock:
            if self._conn is None or self._conn.closed:
                self._conn = _connect(
                    self._conninfo,
                    use_managed_identity=self._use_managed_identity,
                )
                self._conn.autocommit = True
            return self._conn

    def publish(self, channel: str, message: WorkerWakeMessage) -> None:
        notify_channel = logical_wake_channel_to_pg_notify(channel)
        payload = pg_notify_payload_json(message)
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT pg_notify(%s, %s)", (notify_channel, payload))

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and not self._conn.closed:
                self._conn.close()
            self._conn = None


# Back-compat: older imports referred to these names; worker LISTEN path is removed.
postgres_wake_enabled = postgres_wake_publisher_enabled

__all__ = [
    "PostgresWorkerWakePublisher",
    "build_postgres_conninfo",
    "postgres_wake_enabled",
    "postgres_wake_publisher_enabled",
]
