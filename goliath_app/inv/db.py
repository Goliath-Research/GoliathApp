"""PostgreSQL helpers for inventory action handlers."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg


def connect():
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ.get("PGPASSWORD"),
    )


@contextmanager
def db_cursor() -> Iterator[psycopg.Cursor]:
    with connect() as conn:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
