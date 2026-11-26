"""Portal and gateway PostgreSQL clients must verify the server certificate.

The default connection, and any override that does not verify the server
certificate, must fail closed. These tests speak the libpq startup sequence
to a local impostor and fail while the client still sends a password or a
session token to that impostor.
"""

from __future__ import annotations

import importlib.util
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, urlparse

import psycopg
import pytest
from psycopg.rows import dict_row

from goliath_app.portal.client import PortalClient
from goliath_app.portal.connection import build_portal_conninfo
from goliath_worker.postgres_wake import PostgresWorkerWakePublisher, build_postgres_conninfo
from goliath_worker.wake import WorkerWakeMessage
from rest.connection import build_postgres_conninfo as build_gateway_conninfo
from rest.connection import resolve_connection_config

# libpq fe-connect.c DefaultSSLMode and pqcomm.h NEGOTIATE_SSL_CODE / GSS.
_SSL_REQUEST = (1234 << 16) | 5679
_GSS_REQUEST = (1234 << 16) | 5680
_PROTOCOL_3 = 3 << 16
_AUTH_OK = 0
_AUTH_CLEARTEXT = 3

PLACEHOLDER_PASSWORD = "placeholder-portal-password"
PLACEHOLDER_TOKEN = "placeholder-session-token"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_CLEAR = (
    "PGSSLMODE",
    "PGREQUIRESSL",
    "PGSSLROOTCERT",
    "PGSSLCERT",
    "PGSSLKEY",
    "PGSSLCRL",
    "PGSSLCRLDIR",
    "PGSSLNEGOTIATION",
    "PGCHANNELBINDING",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGPASSFILE",
    "PGPASSWORD",
    "POSTGRES_PASSWORD",
    "GOLIATH_PORTAL_DB",
    "GOLIATH_PORTAL_USE_MANAGED_IDENTITY",
    "GOLIATH_DATABASE_URL",
    "WF_DATABASE_URL",
    "WF_USE_MANAGED_IDENTITY",
    "METHYLPIPELINE_DB",
)


def _recvall(conn: socket.socket, count: int) -> bytes:
    buf = b""
    while len(buf) < count:
        chunk = conn.recv(count - len(buf))
        if not chunk:
            raise ConnectionError("eof")
        buf += chunk
    return buf


def _read_untagged(conn: socket.socket) -> bytes:
    header = _recvall(conn, 4)
    length = struct.unpack("!I", header)[0]
    if length < 4 or length > 100_000:
        raise ConnectionError("bad packet length")
    return header + _recvall(conn, length - 4)


def _read_tagged(conn: socket.socket) -> tuple[bytes, bytes]:
    kind = _recvall(conn, 1)
    length = struct.unpack("!I", _recvall(conn, 4))[0]
    if length < 4 or length > 1_000_000:
        raise ConnectionError("bad message length")
    return kind, _recvall(conn, length - 4)


def _send_auth(conn: socket.socket, code: int) -> None:
    conn.sendall(b"R" + struct.pack("!II", 8, code))


def _send_ready(conn: socket.socket, status: bytes) -> None:
    conn.sendall(b"Z" + struct.pack("!I", 5) + status)


def _send_error(conn: socket.socket) -> None:
    body = b"SERROR\x00VERROR\x00C28P01\x00Mauthentication failed\x00\x00"
    conn.sendall(b"E" + struct.pack("!I", 4 + len(body)) + body)


def _send_startup_ok(conn: socket.socket) -> None:
    _send_auth(conn, _AUTH_OK)
    conn.sendall(b"K" + struct.pack("!III", 12, 1, 2))
    for key, value in (
        ("server_version", "18.6"),
        ("client_encoding", "UTF8"),
        ("integer_datetimes", "on"),
    ):
        raw = key.encode() + b"\x00" + value.encode() + b"\x00"
        conn.sendall(b"S" + struct.pack("!I", 4 + len(raw)) + raw)
    _send_ready(conn, b"I")


def _send_begin_complete(conn: socket.socket) -> None:
    body = b"BEGIN\x00"
    conn.sendall(b"C" + struct.pack("!I", 4 + len(body)) + body)
    _send_ready(conn, b"T")


class _Capture:
    def __init__(self) -> None:
        self.password_sent = False
        self.token_sent = False


class _Impostor:
    """Accept libpq connections and record whether secrets arrive."""

    def __init__(self, mode: str, *, complete_startup: bool, request_password: bool) -> None:
        if mode not in ("cleartext", "untrusted-cert"):
            raise ValueError(mode)
        self.mode = mode
        self.complete_startup = complete_startup
        self.request_password = request_password
        self.capture = _Capture()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None
        self._ctx: ssl.SSLContext | None = None
        self.port = 0

    def __enter__(self) -> _Impostor:
        if self.mode == "untrusted-cert":
            self._tmpdir = tempfile.TemporaryDirectory()
            cert = Path(self._tmpdir.name) / "cert.pem"
            key = Path(self._tmpdir.name) / "key.pem"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=impostor.invalid",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            self._ctx = ctx
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        self.port = listener.getsockname()[1]
        self._listener = listener
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._tmpdir is not None:
            self._tmpdir.cleanup()

    def _serve(self) -> None:
        assert self._listener is not None
        self._listener.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _addr = self._listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                self._handle(conn)
            except Exception:
                pass
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(3)
        while True:
            packet = _read_untagged(conn)
            if len(packet) == 8:
                code = struct.unpack("!I", packet[4:])[0]
                if code == _SSL_REQUEST and self.mode == "untrusted-cert":
                    conn.sendall(b"S")
                    assert self._ctx is not None
                    conn = self._ctx.wrap_socket(conn, server_side=True)
                    conn.settimeout(3)
                    continue
                if code in (_SSL_REQUEST, _GSS_REQUEST):
                    conn.sendall(b"N")
                    continue
                return
            if len(packet) >= 8 and struct.unpack("!I", packet[4:8])[0] == _PROTOCOL_3:
                self._after_startup(conn)
                return
            return

    def _after_startup(self, conn: socket.socket) -> None:
        if self.request_password:
            _send_auth(conn, _AUTH_CLEARTEXT)
            kind, payload = _read_tagged(conn)
            if kind == b"p" and payload.rstrip(b"\x00"):
                self.capture.password_sent = True
            del payload
        if not self.complete_startup:
            _send_error(conn)
            return
        _send_startup_ok(conn)
        conn.settimeout(3)
        for _ in range(12):
            kind, payload = _read_tagged(conn)
            if PLACEHOLDER_TOKEN.encode() in payload:
                self.capture.token_sent = True
            is_begin = kind == b"Q" and payload.startswith(b"BEGIN")
            del payload
            if is_begin:
                _send_begin_complete(conn)
                continue
            if kind == b"S":
                return


def _scrub(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_CLEAR:
        monkeypatch.delenv(name, raising=False)


def _point_at(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    _scrub(monkeypatch)
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", str(port))
    monkeypatch.setenv("PGDATABASE", "goliath")
    monkeypatch.setenv("POSTGRES_DB", "goliath")
    monkeypatch.setenv("GOLIATH_PORTAL_USER", "goliath_portal")
    monkeypatch.setenv("GOLIATH_PORTAL_PASSWORD", PLACEHOLDER_PASSWORD)
    monkeypatch.setenv("PGUSER", "goliath_portal")
    monkeypatch.setenv("PGPASSWORD", PLACEHOLDER_PASSWORD)


def _drive(impostor: _Impostor, fn: Callable[[], None]) -> bool:
    outcome: dict[str, bool] = {}

    def run() -> None:
        try:
            fn()
        except Exception:
            outcome["raised"] = True
        else:
            outcome["raised"] = False

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(10)
    if worker.is_alive():
        impostor._stop.set()
        if impostor._listener is not None:
            try:
                impostor._listener.close()
            except OSError:
                pass
        worker.join(2)
        raise AssertionError("database connection attempt did not finish")
    return outcome["raised"]


def _assert_refused(raised: bool, capture: _Capture) -> None:
    assert raised
    assert not capture.password_sent
    assert not capture.token_sent


def _portal_url(port: int, query: str) -> str:
    user = quote("goliath_portal", safe="")
    password = quote(PLACEHOLDER_PASSWORD, safe="")
    suffix = f"?{query}" if query else ""
    return f"postgresql://{user}:{password}@127.0.0.1:{port}/goliath{suffix}"


def _sslmode_of(conninfo: str) -> str | None:
    if "://" in conninfo:
        values = parse_qs(urlparse(conninfo).query).get("sslmode")
        return values[-1] if values else None
    mode = None
    for part in conninfo.split():
        if part.startswith("sslmode="):
            mode = part.split("=", 1)[1]
    return mode


def test_default_portal_url_requests_verify_full(monkeypatch: pytest.MonkeyPatch) -> None:
    _scrub(monkeypatch)
    monkeypatch.setenv("PGHOST", "db.example")
    monkeypatch.setenv("GOLIATH_PORTAL_PASSWORD", PLACEHOLDER_PASSWORD)
    assert _sslmode_of(build_portal_conninfo()) == "verify-full"
    monkeypatch.setenv("GOLIATH_PORTAL_USE_MANAGED_IDENTITY", "1")
    assert _sslmode_of(build_portal_conninfo(use_managed_identity=True)) == "verify-full"


def test_default_gateway_and_worker_urls_request_verify_full(monkeypatch: pytest.MonkeyPatch) -> None:
    _scrub(monkeypatch)
    monkeypatch.setenv("PGHOST", "db.example")
    monkeypatch.setenv("PGPASSWORD", PLACEHOLDER_PASSWORD)
    assert _sslmode_of(build_gateway_conninfo()) == "verify-full"
    assert _sslmode_of(build_postgres_conninfo()) == "verify-full"


@pytest.mark.parametrize("mode", ["cleartext", "untrusted-cert"])
def test_default_portal_client_does_not_disclose_password_or_session_token(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    with _Impostor(mode, complete_startup=True, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)

        def connect() -> None:
            PortalClient().session_touch(PLACEHOLDER_TOKEN)

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


@pytest.mark.parametrize("mode", ["cleartext", "untrusted-cert"])
def test_default_portal_session_open_does_not_disclose_password(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    with _Impostor(mode, complete_startup=False, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)

        def connect() -> None:
            PortalClient().session_open(1)

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


@pytest.mark.parametrize("mode", ["cleartext", "untrusted-cert"])
def test_managed_identity_portal_client_does_not_disclose_session_token(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    with _Impostor(mode, complete_startup=True, request_password=False) as impostor:
        _point_at(monkeypatch, impostor.port)
        monkeypatch.setenv("GOLIATH_PORTAL_USE_MANAGED_IDENTITY", "1")

        def connect() -> None:
            PortalClient().session_touch(PLACEHOLDER_TOKEN)

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


@pytest.mark.parametrize(
    ("query", "mode"),
    [
        ("sslmode=prefer", "cleartext"),
        ("sslmode=prefer", "untrusted-cert"),
        ("sslmode=require", "untrusted-cert"),
        ("sslmode=disable", "cleartext"),
        ("sslmode=allow", "cleartext"),
        ("", "cleartext"),
        ("", "untrusted-cert"),
        ("requiressl=0", "cleartext"),
        ("ssl=true", "untrusted-cert"),
        ("sslmode=verify-full&sslmode=disable", "cleartext"),
        ("sslmode=disable&sslmode=verify-full", "cleartext"),
        ("sslmode=verify-full", "cleartext"),
        ("sslmode=verify-full", "untrusted-cert"),
        ("sslmode=verify-ca", "cleartext"),
        ("sslmode=verify-ca", "untrusted-cert"),
    ],
)
def test_portal_db_override_fails_closed_unless_it_verifies(
    monkeypatch: pytest.MonkeyPatch, query: str, mode: str
) -> None:
    with _Impostor(mode, complete_startup=True, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)
        monkeypatch.setenv("GOLIATH_PORTAL_DB", _portal_url(impostor.port, query))

        def connect() -> None:
            PortalClient().session_touch(PLACEHOLDER_TOKEN)

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


@pytest.mark.parametrize(
    ("query", "mode"),
    [
        ("sslmode=prefer", "cleartext"),
        ("sslmode=require", "untrusted-cert"),
        ("sslmode=verify-full&sslmode=prefer", "untrusted-cert"),
        ("sslmode=verify-full", "untrusted-cert"),
    ],
)
def test_portal_client_conninfo_argument_fails_closed(
    monkeypatch: pytest.MonkeyPatch, query: str, mode: str
) -> None:
    with _Impostor(mode, complete_startup=True, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)
        weak = _portal_url(impostor.port, query)
        monkeypatch.setenv("GOLIATH_PORTAL_DB", _portal_url(impostor.port, "sslmode=verify-full"))

        def connect() -> None:
            PortalClient(weak).session_touch(PLACEHOLDER_TOKEN)

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


def test_portal_keyword_conninfo_prefer_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    with _Impostor("cleartext", complete_startup=False, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)
        conninfo = (
            f"host=127.0.0.1 port={impostor.port} dbname=goliath "
            f"user=goliath_portal password={PLACEHOLDER_PASSWORD} sslmode=prefer"
        )
        monkeypatch.setenv("GOLIATH_PORTAL_DB", conninfo)

        def connect() -> None:
            PortalClient().session_open(1)

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


@pytest.mark.parametrize("mode", ["cleartext", "untrusted-cert"])
def test_gateway_default_connection_does_not_disclose_password(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    with _Impostor(mode, complete_startup=False, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)

        def connect() -> None:
            psycopg.connect(resolve_connection_config().connection_string, row_factory=dict_row)

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


@pytest.mark.parametrize(
    ("env_name", "query", "mode"),
    [
        ("GOLIATH_DATABASE_URL", "sslmode=prefer", "cleartext"),
        ("GOLIATH_DATABASE_URL", "sslmode=require", "untrusted-cert"),
        ("WF_DATABASE_URL", "sslmode=disable", "cleartext"),
        ("GOLIATH_DATABASE_URL", "sslmode=verify-full", "untrusted-cert"),
    ],
)
def test_gateway_url_override_fails_closed(
    monkeypatch: pytest.MonkeyPatch, env_name: str, query: str, mode: str
) -> None:
    with _Impostor(mode, complete_startup=False, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)
        monkeypatch.setenv(env_name, _portal_url(impostor.port, query))

        def connect() -> None:
            psycopg.connect(resolve_connection_config().connection_string, row_factory=dict_row)

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


def test_gateway_connection_string_argument_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    with _Impostor("untrusted-cert", complete_startup=False, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)
        weak = _portal_url(impostor.port, "sslmode=require")

        def connect() -> None:
            config = resolve_connection_config(connection_string=weak)
            psycopg.connect(config.connection_string, row_factory=dict_row)

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


@pytest.mark.parametrize("mode", ["cleartext", "untrusted-cert"])
def test_worker_wake_default_connection_does_not_disclose_password(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    with _Impostor(mode, complete_startup=False, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)

        def connect() -> None:
            publisher = PostgresWorkerWakePublisher(build_postgres_conninfo())
            publisher.publish(
                "goliath.wake.v1.pool.placeholder",
                WorkerWakeMessage(wake_id="placeholder-wake", reason="placeholder"),
            )

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)


def _load_inventory() -> object:
    name = "db_schema_inventory"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = _REPO_ROOT / "scripts" / "db_schema_inventory.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode", ["cleartext", "untrusted-cert"])
def test_schema_inventory_does_not_disclose_password(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    inventory = _load_inventory()
    with _Impostor(mode, complete_startup=False, request_password=True) as impostor:
        _point_at(monkeypatch, impostor.port)

        def connect() -> None:
            conn, _database = inventory._pg_connect()  # type: ignore[attr-defined]
            conn.close()

        raised = _drive(impostor, connect)
        _assert_refused(raised, impostor.capture)
