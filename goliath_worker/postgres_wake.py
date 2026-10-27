"""Postgres LISTEN/NOTIFY broker for dual worker activation."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import quote

import psycopg
from psycopg import sql

from goliath_worker.wake import (
    NullWorkerWakeSubscriber,
    WorkerWakeMessage,
    logical_wake_channel_to_pg_notify,
)


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in ("1", "true", "yes")


def postgres_wake_enabled() -> bool:
    """True when worker or gateway should use Postgres NOTIFY for wakes."""
    return _env_flag("WF_WAKE_POSTGRES") or _env_flag("WORKER_WAKE_POSTGRES")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def build_postgres_conninfo(*, use_managed_identity: bool = False) -> str:
    override = _env("METHYLPIPELINE_DB")
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
        payload = json.dumps(message.to_json(), separators=(",", ":"))
        conn = self._ensure_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT pg_notify(%s, %s)", (notify_channel, payload))

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and not self._conn.closed:
                self._conn.close()
            self._conn = None


class PostgresWorkerWakeSubscriber:
    """Worker-side ``LISTEN`` on a dedicated connection (never blocks gateway claim paths)."""

    def __init__(
        self,
        conninfo: str,
        *,
        use_managed_identity: bool = False,
    ) -> None:
        self._conninfo = conninfo
        self._use_managed_identity = use_managed_identity
        self._wake_queue: queue.Queue[WorkerWakeMessage] = queue.Queue()
        self._conn: Optional[psycopg.Connection[Any]] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def subscribe(
        self,
        channels: Iterable[str],
        *,
        session_token: str,
        worker_id: int,
    ) -> None:
        if not (session_token or "").strip():
            raise ValueError("subscribe requires a non-empty worker session_token")
        if worker_id <= 0:
            raise ValueError("subscribe requires a positive worker_id")

        notify_channels = [logical_wake_channel_to_pg_notify(ch) for ch in channels]
        if not notify_channels:
            return

        self.unsubscribe()
        self._stop_event.clear()
        while not self._wake_queue.empty():
            try:
                self._wake_queue.get_nowait()
            except queue.Empty:
                break

        conn = _connect(self._conninfo, use_managed_identity=self._use_managed_identity)
        conn.autocommit = True
        with conn.cursor() as cur:
            for notify_ch in notify_channels:
                cur.execute(sql.SQL("LISTEN {}").format(sql.Identifier(notify_ch)))

        self._conn = conn
        self._listener_thread = threading.Thread(
            target=self._listen_loop,
            name="goliath-wake-listener",
            daemon=True,
        )
        self._listener_thread.start()

    def _listen_loop(self) -> None:
        conn = self._conn
        if conn is None:
            return
        try:
            for notify in conn.notifies():
                if self._stop_event.is_set():
                    break
                try:
                    data = json.loads(notify.payload)
                    self._wake_queue.put(WorkerWakeMessage.from_json(data))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
        except psycopg.OperationalError:
            pass

    def unsubscribe(self) -> None:
        self._stop_event.set()
        thread = self._listener_thread
        conn = self._conn
        self._listener_thread = None
        self._conn = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        if conn is not None and not conn.closed:
            try:
                conn.close()
            except psycopg.Error:
                pass

    def wait_for_wake(self, *, timeout_seconds: Optional[float] = None) -> Optional[WorkerWakeMessage]:
        try:
            return self._wake_queue.get(timeout=timeout_seconds)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.unsubscribe()


def resolve_postgres_wake_conninfo(explicit: Optional[str] = None) -> str:
    """DSN for LISTEN/NOTIFY (defaults to ``WORKER_WAKE_PG_DSN`` or gateway ``METHYLPIPELINE_DB`` / ``PG*``)."""
    override = (explicit or _env("WORKER_WAKE_PG_DSN") or _env("METHYLPIPELINE_DB")).strip()
    if override:
        return override
    use_mi = _env_flag("WF_USE_MANAGED_IDENTITY")
    return build_postgres_conninfo(use_managed_identity=use_mi)


def resolve_worker_wake_subscriber() -> PostgresWorkerWakeSubscriber | NullWorkerWakeSubscriber:
    if not postgres_wake_enabled():
        return NullWorkerWakeSubscriber()
    use_mi = _env_flag("WF_USE_MANAGED_IDENTITY")
    return PostgresWorkerWakeSubscriber(
        resolve_postgres_wake_conninfo(),
        use_managed_identity=use_mi,
    )
