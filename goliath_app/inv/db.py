"""PostgreSQL helpers for inventory action handlers."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def connect():
    host = _env("PGHOST") or _env("POSTGRES_HOST", "localhost")
    port = _env("PGPORT") or _env("POSTGRES_PORT", "5432")
    dbname = _env("PGDATABASE") or _env("POSTGRES_DB", "goliath")
    user = _env("PGUSER") or _env("POSTGRES_USER", "postgres")
    password = _env("PGPASSWORD") or _env("POSTGRES_PASSWORD") or None
    return psycopg.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
    )


@contextmanager
def db_cursor() -> Iterator[psycopg.Cursor]:
    with connect() as conn:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
