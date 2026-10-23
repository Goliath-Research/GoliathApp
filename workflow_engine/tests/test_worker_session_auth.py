"""PostgreSQL integration tests for P3 worker session auth (when POSTGRES_* is set)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import unittest
from pathlib import Path

WF_ENGINE = Path(__file__).resolve().parents[1]
SQL_PG = WF_ENGINE / "sql_pg"
sys.path.insert(0, str(WF_ENGINE))

from rest.db.postgres import PostgresGatewayDb  # noqa: E402
from rest.db.base import WorkerCallAuth  # noqa: E402
from tests.parity.run_parity import (  # noqa: E402
    _pg_dsn,
    _pg_env,
    _psql,
    _psql_query,
    deploy_postgres,
    seed_minimal_workflow,
    start_instance,
)


def _postgres_available() -> bool:
    if os.environ.get("SKIP_PG_INTEGRATION", "").strip().lower() in ("1", "true", "yes"):
        return False
    dsn = _pg_dsn()
    try:
        proc = subprocess.run(
            ["psql", dsn, "-t", "-A", "-c", "SELECT 1"],
            capture_output=True,
            text=True,
            env=_pg_env(),
            timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@unittest.skipUnless(_postgres_available(), "PostgreSQL not available")
class WorkerSessionAuthIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dsn = _pg_dsn()
        deploy_postgres(cls.dsn)
        _psql_query(
            cls.dsn,
            "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA wf TO PUBLIC; "
            "GRANT USAGE ON SCHEMA wf TO PUBLIC; "
            "GRANT USAGE ON SCHEMA \"RBAC\" TO PUBLIC; "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA \"RBAC\" TO PUBLIC; "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA wf TO PUBLIC; "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA cfg TO PUBLIC;",
        )

    def setUp(self) -> None:
        self.version_id, self.worker_id, self.identity = seed_minimal_workflow(self.dsn)
        _psql_query(
            self.dsn,
            f"UPDATE wf.worker_token SET bound_client_ip = '127.0.0.1' WHERE worker_id = {self.worker_id};",
        )
        self.db = PostgresGatewayDb(self.dsn)
        opened = self.db.worker_open_session(self.identity, "127.0.0.1")
        self.session = str(opened["session_token"])
        self.auth = WorkerCallAuth(
            worker_id=self.worker_id,
            session_token=self.session,
            identity_token=self.identity,
            client_ip="127.0.0.1",
        )

    def tearDown(self) -> None:
        self.db.close()

    def test_missing_session_fails(self) -> None:
        bad = WorkerCallAuth(
            worker_id=self.worker_id,
            session_token="not-a-real-session",
            identity_token=self.identity,
            client_ip="127.0.0.1",
        )
        with self.assertRaises(Exception):
            self.db.worker_request_task(bad, "test-cap", 60)

    def test_missing_identity_fails(self) -> None:
        bad = WorkerCallAuth(
            worker_id=self.worker_id,
            session_token=self.session,
            identity_token="bad-identity",
            client_ip="127.0.0.1",
        )
        with self.assertRaises(Exception):
            self.db.worker_request_task(bad, "test-cap", 60)

    def test_wrong_ip_fails(self) -> None:
        bad = WorkerCallAuth(
            worker_id=self.worker_id,
            session_token=self.session,
            identity_token=self.identity,
            client_ip="198.51.100.1",
        )
        with self.assertRaises(Exception):
            self.db.worker_request_task(bad, "test-cap", 60)

    def test_only_hashes_stored(self) -> None:
        digest = hashlib.sha256(self.identity.encode()).hexdigest()
        row = _psql_query(
            self.dsn,
            "SELECT encode(token_hash, 'hex') FROM wf.worker_token WHERE worker_id = "
            f"{self.worker_id} LIMIT 1;",
        )
        self.assertEqual(row.lower(), digest.lower())
        self.assertNotIn(
            self.identity,
            _psql_query(self.dsn, "SELECT token_hash::text FROM wf.worker_token LIMIT 5;"),
        )

    def test_missed_heartbeat_marks_failed_and_reclaims(self) -> None:
        start_instance(self.dsn, self.version_id)
        claim = self.db.worker_request_task(self.auth, "test-cap", 300)
        self.assertTrue(claim.get("has_task"), claim)
        _psql_query(
            self.dsn,
            f"""
            UPDATE "RBAC"."SessionTokens" st
            SET "LastRefreshedAtUtc" = (now() AT TIME ZONE 'utc') - interval '1 hour'
            FROM "RBAC"."Sessions" s
            WHERE st."SessionID" = s."ID" AND s."UserID" = (
              SELECT rbac_user_id FROM wf.worker WHERE id = {self.worker_id}
            );
            """,
        )
        with self.assertRaises(Exception):
            self.db.worker_request_task(self.auth, "test-cap", 300)
        status = _psql_query(
            self.dsn,
            f"SELECT status FROM wf.worker WHERE id = {self.worker_id};",
        )
        self.assertEqual(status, "FAILED")

    def test_resession_from_wrong_ip_fails(self) -> None:
        with self.assertRaises(Exception):
            self.db.worker_open_session(self.identity, "198.51.100.1")

    def test_goliath_portal_cannot_select_worker_table(self) -> None:
        roles_sql = SQL_PG / "database_gateway_roles.sql"
        if roles_sql.is_file():
            _psql(self.dsn, ["-f", str(roles_sql)])
        proc = _psql(
            self.dsn,
            ["-t", "-A", "-c", "SET ROLE goliath_portal; SELECT COUNT(*) FROM wf.worker;"],
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
