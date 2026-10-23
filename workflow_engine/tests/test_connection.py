"""Tests for workflow gateway connection configuration."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REST_DIR = Path(__file__).resolve().parents[1] / "rest"
sys.path.insert(0, str(REST_DIR))

from connection import (  # noqa: E402
    build_postgres_conninfo,
    resolve_connection_config,
    resolve_schema_name,
)


class ConnectionConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved)

    def test_schema_default(self) -> None:
        os.environ.pop("WF_SCHEMA", None)
        self.assertEqual(resolve_schema_name(), "wf")

    def test_postgres_conninfo_from_env(self) -> None:
        os.environ.pop("METHYLPIPELINE_DB", None)
        os.environ.pop("PGSSLMODE", None)
        os.environ.update(
            {
                "POSTGRES_HOST": "db.example.com",
                "POSTGRES_PORT": "5433",
                "POSTGRES_DB": "methyl",
                "POSTGRES_USER": "dba",
                "POSTGRES_PASSWORD": "secret",
            }
        )
        self.assertEqual(
            build_postgres_conninfo(),
            "postgresql://dba:secret@db.example.com:5433/methyl?sslmode=prefer",
        )

    def test_postgres_conninfo_honors_pgsslmode(self) -> None:
        os.environ.pop("METHYLPIPELINE_DB", None)
        os.environ.update(
            {
                "POSTGRES_HOST": "db.example.com",
                "POSTGRES_PORT": "5433",
                "POSTGRES_DB": "methyl",
                "POSTGRES_USER": "dba",
                "POSTGRES_PASSWORD": "secret",
                "PGSSLMODE": "disable",
            }
        )
        self.assertEqual(
            build_postgres_conninfo(),
            "postgresql://dba:secret@db.example.com:5433/methyl?sslmode=disable",
        )

    def test_postgres_conninfo_prefers_libpq_names(self) -> None:
        os.environ.pop("METHYLPIPELINE_DB", None)
        os.environ.update(
            {
                "PGHOST": "pglib.example.com",
                "PGPORT": "5434",
                "PGDATABASE": "goliath",
                "PGUSER": "app",
                "PGPASSWORD": "pw",
            }
        )
        self.assertEqual(
            build_postgres_conninfo(),
            "postgresql://app:pw@pglib.example.com:5434/goliath?sslmode=prefer",
        )

    def test_methylpipeline_db_override(self) -> None:
        os.environ["METHYLPIPELINE_DB"] = "postgresql://u:p@host/db"
        cfg = resolve_connection_config()
        self.assertEqual(cfg.connection_string, "postgresql://u:p@host/db")

    def test_managed_identity_flag(self) -> None:
        os.environ["WF_USE_MANAGED_IDENTITY"] = "1"
        cfg = resolve_connection_config()
        self.assertTrue(cfg.use_managed_identity)

    def test_postgres_conninfo_sslmode_when_mi(self) -> None:
        os.environ.pop("METHYLPIPELINE_DB", None)
        os.environ.pop("PGSSLMODE", None)
        os.environ.update(
            {
                "POSTGRES_HOST": "pg.example.com",
                "POSTGRES_PORT": "5432",
                "POSTGRES_DB": "methyl",
                "POSTGRES_USER": "mi-principal",
                "POSTGRES_PASSWORD": "ignored",
            }
        )
        conn = build_postgres_conninfo(use_managed_identity=True)
        self.assertEqual(
            conn,
            "postgresql://mi-principal@pg.example.com:5432/methyl?sslmode=prefer",
        )
        self.assertNotIn("ignored", conn)


if __name__ == "__main__":
    unittest.main()
