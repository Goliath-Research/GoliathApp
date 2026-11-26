"""PostgreSQL helpers for inventory action handlers."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg

INVENTORY_DB_ROLE = "goliath_inv"
_SUPERUSER_ROLE = "postgres"


class InventoryDatabaseRoleError(RuntimeError):
    """The inventory connection resolved to a role it must not use."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _is_superuser(conn: psycopg.Connection) -> bool:
    # current_user differs from session_user when PGOPTIONS or a service file sets role=.
    row = conn.execute(
        """
        SELECT coalesce(bool_or(r.rolsuper), true)
        FROM pg_catalog.pg_roles r
        WHERE r.rolname IN (session_user, current_user)
        """
    ).fetchone()
    conn.rollback()
    return conn.info.parameter_status("is_superuser") != "off" or row is None or bool(row[0])


def connect() -> psycopg.Connection:
    host = _env("PGHOST") or _env("POSTGRES_HOST", "localhost")
    port = _env("PGPORT") or _env("POSTGRES_PORT", "5432")
    dbname = _env("PGDATABASE") or _env("POSTGRES_DB", "goliath")
    user = _env("PGUSER") or _env("POSTGRES_USER") or INVENTORY_DB_ROLE
    if user == _SUPERUSER_ROLE:
        raise InventoryDatabaseRoleError(
            f"inventory handlers must not connect as {_SUPERUSER_ROLE!r}; "
            f"set PGUSER to the {INVENTORY_DB_ROLE!r} role"
        )
    password = _env("PGPASSWORD") or _env("POSTGRES_PASSWORD") or None
    # Keyword arguments take precedence over PGSSLMODE, so the environment cannot downgrade TLS.
    conn = psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        sslmode="verify-full",
    )
    if _is_superuser(conn):
        conn.close()
        raise InventoryDatabaseRoleError(
            f"inventory handlers must not connect as a superuser (role {user!r})"
        )
    return conn


@contextmanager
def db_cursor() -> Iterator[psycopg.Cursor]:
    with connect() as conn:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
