"""Inventory stock actions must not open PostgreSQL as a superuser or without verified TLS.

These tests exercise ``goliath_app.execution.local.execute_action`` for every
inventory stock handler (``inv.stock.receive``, ``inv.stock.adjust``, and
``inv.stock.issue``). That is the function the local workflow runner calls for
catalog actions. Each test points the handler at a local impostor that speaks
the PostgreSQL startup sequence: an SSLRequest, an optional TLS handshake, a
startup packet, and a cleartext password request.

The tests are the spec for the fix. They fail while ``goliath_app.inv.db.connect``
omits ``sslmode`` (libpq's compiled default is ``prefer``) and defaults the user
to ``postgres``. They pass when that connection passes ``sslmode=verify-full``,
defaults an unset user to the least-privilege role ``goliath_inv``, and refuses
to connect when the resolved user is ``postgres``, before any socket is opened.

Sibling connection builders that set ``sslmode`` explicitly to ``prefer`` are a
separate path and are not covered here: ``workflow_engine/rest/connection.py``,
``goliath_app/portal/connection.py``, ``goliath_worker/postgres_wake.py``, and
``scripts/db_schema_inventory.py``.
"""

from __future__ import annotations

import socket
import ssl
import subprocess
import threading
from pathlib import Path
from typing import Mapping

import psycopg
import pytest

from goliath_app.actions.registry import find_action, reload_action_catalog
from goliath_app.execution.local import execute_action

# Obvious placeholder. Not a credential used by any deployment.
_PASSWORD_PLACEHOLDER = "placeholder-not-a-secret"
_INVENTORY_ROLE = "goliath_inv"
_SUPERUSER_ROLE = "postgres"
_SSL_REQUEST_CODE = (1234 << 16) | 5679

_STOCK_ACTIONS: tuple[tuple[str, dict[str, object]], ...] = (
    (
        "inv.stock.receive",
        {
            "organization_id": 1,
            "user_id": 1,
            "po_line_id": 1,
            "bin_id": 1,
            "qty": "1",
        },
    ),
    (
        "inv.stock.adjust",
        {
            "organization_id": 1,
            "user_id": 1,
            "stock_lot_id": 1,
            "qty_delta": "1",
            "reason_code": "cycle",
        },
    ),
    (
        "inv.stock.issue",
        {
            "organization_id": 1,
            "user_id": 1,
            "stock_lot_id": 1,
            "qty": "1",
            "ref_type": "ref",
            "ref_id": "1",
        },
    ),
)

_ENV_KEYS = (
    "PGHOST",
    "PGPORT",
    "PGUSER",
    "PGPASSWORD",
    "PGDATABASE",
    "PGSSLMODE",
    "PGSSLROOTCERT",
    "PGSSLNEGOTIATION",
    "PGREQUIRESSL",
    "PGSERVICE",
    "PGPASSFILE",
    "PGCHANNELBINDING",
    "PGGSSENCMODE",
    "PGCONNECT_TIMEOUT",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
)


class DatabaseImpostor:
    """Accept libpq connections and record whether a password message arrives.

    ``mode`` is ``refuse-ssl`` (reply ``N`` to SSLRequest), ``tls`` (reply ``S``
    and present ``certfile``), or ``any`` (do whichever the client asks for).
    The password bytes are not stored.
    """

    def __init__(self, mode: str, certfile: Path | None = None, keyfile: Path | None = None) -> None:
        if mode not in ("refuse-ssl", "tls", "any"):
            raise ValueError(mode)
        self._mode = mode
        self._certfile = certfile
        self._keyfile = keyfile
        self.received_password = False
        self.users: list[str] = []
        self.accepted = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._handlers: list[threading.Thread] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = int(self._sock.getsockname()[1])
        self._thread = threading.Thread(target=self._accept_loop, name="inv-db-impostor", daemon=True)

    def __enter__(self) -> DatabaseImpostor:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        for handler in self._handlers:
            handler.join(timeout=2)
        self._sock.close()

    def _accept_loop(self) -> None:
        self._sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with self._lock:
                self.accepted += 1
            handler = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            self._handlers.append(handler)
            handler.start()

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(2)
        try:
            length, body = _read_packet(conn)
            if length == 8 and int.from_bytes(body, "big") == _SSL_REQUEST_CODE:
                if self._mode == "refuse-ssl" or self._certfile is None:
                    conn.sendall(b"N")
                    length, body = _read_packet(conn)
                    self._startup_and_password(conn, body)
                else:
                    conn.sendall(b"S")
                    tls = _server_tls(self._certfile, self._keyfile).wrap_socket(conn, server_side=True)
                    try:
                        _length, startup = _read_packet(tls)
                        self._startup_and_password(tls, startup)
                    finally:
                        tls.close()
                    return
            else:
                self._startup_and_password(conn, body)
        except (OSError, EOFError, ValueError):
            return
        finally:
            conn.close()

    def _startup_and_password(self, sock: socket.socket, startup_body: bytes) -> None:
        params = _startup_params(startup_body)
        user = params.get("user")
        if user is not None:
            with self._lock:
                self.users.append(user)
        # AuthenticationCleartextPassword: type 'R', length 8, auth code 3.
        sock.sendall(b"R" + (8).to_bytes(4, "big") + (3).to_bytes(4, "big"))
        kind = _read_exact(sock, 1)
        if kind != b"p":
            return
        length, body = _read_packet_rest(sock)
        if length < 5 or not body.endswith(b"\x00"):
            return
        with self._lock:
            self.received_password = True


def _read_exact(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        piece = sock.recv(remaining)
        if not piece:
            raise EOFError
        chunks.append(piece)
        remaining -= len(piece)
    return b"".join(chunks)


def _read_packet(sock: socket.socket) -> tuple[int, bytes]:
    raw_length = _read_exact(sock, 4)
    length = int.from_bytes(raw_length, "big")
    if length < 4 or length > 100_000:
        raise ValueError(f"unexpected packet length {length}")
    return length, _read_exact(sock, length - 4)


def _read_packet_rest(sock: socket.socket) -> tuple[int, bytes]:
    """Read a typed message whose type byte was already consumed."""
    raw_length = _read_exact(sock, 4)
    length = int.from_bytes(raw_length, "big")
    if length < 4 or length > 100_000:
        raise ValueError(f"unexpected packet length {length}")
    return length, _read_exact(sock, length - 4)


def _startup_params(body: bytes) -> dict[str, str]:
    if len(body) < 4:
        return {}
    fields = body[4:].split(b"\x00")
    params: dict[str, str] = {}
    index = 0
    while index + 1 < len(fields):
        key = fields[index]
        if key == b"":
            break
        params[key.decode("utf-8", "replace")] = fields[index + 1].decode("utf-8", "replace")
        index += 2
    return params


def _server_tls(certfile: Path, keyfile: Path | None) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile, keyfile)
    return context


def _openssl(*args: str) -> None:
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def _write_certs(directory: Path) -> dict[str, Path]:
    ca_key = directory / "ca.key"
    ca_crt = directory / "ca.crt"
    _openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(ca_key),
        "-out",
        str(ca_crt),
        "-days",
        "1",
        "-subj",
        "/CN=inventory-test-ca",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
    )
    matching = _signed_cert(directory, ca_crt, ca_key, "match", "IP:127.0.0.1", "/CN=inventory-db")
    wrong_host = _signed_cert(
        directory,
        ca_crt,
        ca_key,
        "wrong",
        "DNS:not-the-database.example",
        "/CN=not-the-database.example",
    )
    untrusted_key = directory / "untrusted.key"
    untrusted_crt = directory / "untrusted.crt"
    _openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(untrusted_key),
        "-out",
        str(untrusted_crt),
        "-days",
        "1",
        "-subj",
        "/CN=untrusted",
        "-addext",
        "subjectAltName=IP:127.0.0.1",
    )
    return {
        "ca": ca_crt,
        "match_crt": matching[0],
        "match_key": matching[1],
        "wrong_crt": wrong_host[0],
        "wrong_key": wrong_host[1],
        "untrusted_crt": untrusted_crt,
        "untrusted_key": untrusted_key,
    }


def _signed_cert(
    directory: Path,
    ca_crt: Path,
    ca_key: Path,
    name: str,
    san: str,
    subject: str,
) -> tuple[Path, Path]:
    key = directory / f"{name}.key"
    csr = directory / f"{name}.csr"
    crt = directory / f"{name}.crt"
    _openssl(
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-keyout",
        str(key),
        "-out",
        str(csr),
        "-subj",
        subject,
        "-addext",
        f"subjectAltName={san}",
    )
    _openssl(
        "x509",
        "-req",
        "-in",
        str(csr),
        "-CA",
        str(ca_crt),
        "-CAkey",
        str(ca_key),
        "-CAcreateserial",
        "-out",
        str(crt),
        "-days",
        "1",
        "-copy_extensions",
        "copy",
    )
    return crt, key


@pytest.fixture(scope="module")
def certs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return _write_certs(tmp_path_factory.mktemp("inv-certs"))


@pytest.fixture(autouse=True)
def _catalog() -> None:
    reload_action_catalog()


def _scrub_db_env(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "3")
    monkeypatch.setenv("POSTGRES_PASSWORD", _PASSWORD_PLACEHOLDER)


def _point_at(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", str(port))
    monkeypatch.setenv("PGDATABASE", "goliath")


def _run_stock_action(action_name: str, payload: Mapping[str, object]) -> None:
    spec = find_action(action_name)
    assert spec is not None, action_name
    assert spec.in_process_handler
    execute_action(spec.capability or action_name, action_name, payload)


@pytest.mark.parametrize(("action_name", "payload"), _STOCK_ACTIONS, ids=("receive", "adjust", "issue"))
def test_stock_action_does_not_send_password_when_server_refuses_ssl(
    action_name: str,
    payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _scrub_db_env(monkeypatch, tmp_path)
    with DatabaseImpostor("refuse-ssl") as impostor:
        _point_at(monkeypatch, impostor.port)
        with pytest.raises(psycopg.OperationalError):
            _run_stock_action(action_name, payload)
        assert impostor.received_password is False


@pytest.mark.parametrize(("action_name", "payload"), _STOCK_ACTIONS, ids=("receive", "adjust", "issue"))
def test_stock_action_does_not_send_password_when_pgsslmode_disables_tls(
    action_name: str,
    payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _scrub_db_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PGSSLMODE", "disable")
    with DatabaseImpostor("any") as impostor:
        _point_at(monkeypatch, impostor.port)
        with pytest.raises(psycopg.OperationalError):
            _run_stock_action(action_name, payload)
        assert impostor.received_password is False


@pytest.mark.parametrize(("action_name", "payload"), _STOCK_ACTIONS, ids=("receive", "adjust", "issue"))
def test_stock_action_does_not_send_password_to_untrusted_certificate(
    action_name: str,
    payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    certs: dict[str, Path],
) -> None:
    _scrub_db_env(monkeypatch, tmp_path)
    with DatabaseImpostor("tls", certs["untrusted_crt"], certs["untrusted_key"]) as impostor:
        _point_at(monkeypatch, impostor.port)
        with pytest.raises(psycopg.OperationalError):
            _run_stock_action(action_name, payload)
        assert impostor.received_password is False


@pytest.mark.parametrize(("action_name", "payload"), _STOCK_ACTIONS, ids=("receive", "adjust", "issue"))
def test_stock_action_does_not_send_password_when_certificate_name_does_not_match(
    action_name: str,
    payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    certs: dict[str, Path],
) -> None:
    _scrub_db_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PGSSLROOTCERT", str(certs["ca"]))
    with DatabaseImpostor("tls", certs["wrong_crt"], certs["wrong_key"]) as impostor:
        _point_at(monkeypatch, impostor.port)
        with pytest.raises(psycopg.OperationalError):
            _run_stock_action(action_name, payload)
        assert impostor.received_password is False


@pytest.mark.parametrize(("action_name", "payload"), _STOCK_ACTIONS, ids=("receive", "adjust", "issue"))
def test_unset_user_connects_as_inventory_role(
    action_name: str,
    payload: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    certs: dict[str, Path],
) -> None:
    _scrub_db_env(monkeypatch, tmp_path)
    monkeypatch.setenv("PGSSLROOTCERT", str(certs["ca"]))
    with DatabaseImpostor("tls", certs["match_crt"], certs["match_key"]) as impostor:
        _point_at(monkeypatch, impostor.port)
        with pytest.raises(psycopg.OperationalError):
            _run_stock_action(action_name, payload)
        assert impostor.users == [_INVENTORY_ROLE]


@pytest.mark.parametrize(("action_name", "payload"), _STOCK_ACTIONS, ids=("receive", "adjust", "issue"))
@pytest.mark.parametrize(
    "env_key",
    ("PGUSER", "POSTGRES_USER"),
    ids=("pguser", "postgres_user"),
)
def test_refuses_postgres_superuser_before_connecting(
    action_name: str,
    payload: dict[str, object],
    env_key: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    certs: dict[str, Path],
) -> None:
    _scrub_db_env(monkeypatch, tmp_path)
    monkeypatch.setenv(env_key, _SUPERUSER_ROLE)
    monkeypatch.setenv("PGSSLROOTCERT", str(certs["ca"]))
    with DatabaseImpostor("tls", certs["match_crt"], certs["match_key"]) as impostor:
        _point_at(monkeypatch, impostor.port)
        with pytest.raises(Exception) as caught:
            _run_stock_action(action_name, payload)
        assert not isinstance(caught.value, AssertionError)
        assert impostor.accepted == 0
        assert impostor.received_password is False
        assert impostor.users == []
