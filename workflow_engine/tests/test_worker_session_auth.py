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

from rest.db.base import WorkerCallAuth  # noqa: E402
from rest.db.postgres import PostgresGatewayDb  # noqa: E402
from tests.helpers import pg_integration  # noqa: E402

_pg_dsn = pg_integration.pg_dsn
_pg_env = pg_integration.pg_env
_psql = pg_integration.psql
_psql_query = pg_integration.psql_query
_apply_schema_scripts = pg_integration.apply_schema_scripts
seed_minimal_workflow = pg_integration.seed_minimal_workflow
_postgres_available = pg_integration.postgres_available
shutil_which = pg_integration.shutil_which_cmd


@unittest.skipUnless(_postgres_available(), "PostgreSQL not available")
class WorkerSessionAuthIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dsn = _pg_dsn()
        _apply_schema_scripts(cls.dsn)
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
        _psql_query(
            self.dsn,
            f"""
            UPDATE wf.worker
            SET capabilities = '["test-cap", "device.adapter.ingest"]'::jsonb,
                event_ingest_binding = '{{"source": "pytest-worker-ingest", "org_key": "*", "event_types": ["*"]}}'::jsonb
            WHERE id = {self.worker_id};
            """,
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

    def test_missed_heartbeat_marks_failed(self) -> None:
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
        _psql_query(self.dsn, "CALL wf.wf_worker_expire_stale_sessions();")
        status = _psql_query(
            self.dsn,
            f"SELECT status FROM wf.worker WHERE id = {self.worker_id};",
        )
        self.assertEqual(status, "FAILED")
        with self.assertRaises(Exception):
            self.db.worker_request_task(self.auth, "test-cap", 300)

    def test_resession_from_wrong_ip_fails(self) -> None:
        with self.assertRaises(Exception):
            self.db.worker_open_session(self.identity, "198.51.100.1")

    def test_worker_ingest_event_authenticated(self) -> None:
        result = self.db.ingest_event_worker(
            self.auth,
            event_type="device.adapter.test.v1",
            source="pytest-worker-ingest",
            idempotency_key="idem-sp-worker-ingest-1",
            payload_json={"probe": True, "organization_key": "org-a"},
        )
        self.assertIn("event_id", result)
        self.assertFalse(result.get("duplicate", True))
        dup = self.db.ingest_event_worker(
            self.auth,
            event_type="device.adapter.test.v1",
            source="pytest-worker-ingest",
            idempotency_key="idem-sp-worker-ingest-1",
            payload_json={"probe": False, "organization_key": "org-a"},
        )
        self.assertTrue(dup.get("duplicate", False))

    def test_worker_ingest_event_binding_mismatch_denied(self) -> None:
        from rest.db.base import EventIngestForbidden

        with self.assertRaises(EventIngestForbidden):
            self.db.ingest_event_worker(
                self.auth,
                event_type="device.adapter.test.v1",
                source="wrong-source",
                idempotency_key="idem-binding",
                payload_json={"organization_key": "org-a"},
            )

    def test_worker_ingest_event_missing_capability_denied(self) -> None:
        from rest.db.base import EventIngestForbidden

        _psql_query(
            self.dsn,
            f"UPDATE wf.worker SET capabilities = '[]'::jsonb WHERE id = {self.worker_id};",
        )
        with self.assertRaises(EventIngestForbidden):
            self.db.ingest_event_worker(
                self.auth,
                event_type="device.adapter.test.v1",
                source="pytest-worker-ingest",
                idempotency_key="idem-cap",
                payload_json={"organization_key": "org-a"},
            )

    def test_worker_ingest_event_wrong_ip_fails(self) -> None:
        bad = WorkerCallAuth(
            worker_id=self.worker_id,
            session_token=self.session,
            identity_token=self.identity,
            client_ip="198.51.100.1",
        )
        with self.assertRaises(Exception):
            self.db.ingest_event_worker(
                bad,
                event_type="device.adapter.test.v1",
                source="pytest-worker-ingest",
                idempotency_key="idem-bad-ip",
                payload_json={"organization_key": "org-a"},
            )

    def test_goliath_portal_has_no_cfg_schema_usage(self) -> None:
        roles_sql = SQL_PG / "database_gateway_roles.sql"
        if roles_sql.is_file():
            _psql(self.dsn, ["-f", str(roles_sql)])
        can_cfg = _psql_query(
            self.dsn,
            "SELECT has_schema_privilege('goliath_portal', 'cfg', 'USAGE');",
        )
        self.assertEqual(can_cfg, "f")
        can_portal = _psql_query(
            self.dsn,
            "SELECT has_schema_privilege('goliath_portal', 'portal', 'USAGE');",
        )
        self.assertEqual(can_portal, "t")


if __name__ == "__main__":
    unittest.main()
