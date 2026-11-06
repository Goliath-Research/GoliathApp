"""PostgreSQL integration: event → WAIT resume, SCHEDULE → observe claim, API key + binding auth."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

WF_ENGINE = Path(__file__).resolve().parents[1]
SQL_PG = WF_ENGINE / "sql_pg"
sys.path.insert(0, str(WF_ENGINE))

from rest.db.base import EventIngestForbidden, WorkerCallAuth  # noqa: E402
from rest.db.postgres import PostgresGatewayDb  # noqa: E402
from tests.helpers import pg_integration  # noqa: E402

_apply_schema_scripts = pg_integration.apply_schema_scripts
_pg_dsn = pg_integration.pg_dsn
_pg_env = pg_integration.pg_env
_postgres_available = pg_integration.postgres_available
_psql_query = pg_integration.psql_query
seed_minimal_workflow = pg_integration.seed_minimal_workflow


def _digest_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


@unittest.skipUnless(_postgres_available(), "PostgreSQL not available")
class DeviceAdapterInheritanceFlowTests(unittest.TestCase):
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
        self.db = PostgresGatewayDb(self.dsn)
        self.version_id, self.worker_id, self.identity = seed_minimal_workflow(self.dsn)
        _psql_query(
            self.dsn,
            f"UPDATE wf.worker_token SET bound_client_ip = '127.0.0.1' WHERE worker_id = {self.worker_id};",
        )
        _psql_query(
            self.dsn,
            f"""
            UPDATE wf.worker
            SET capabilities = '["test-cap", "device.adapter.ingest", "device.adapter"]'::jsonb,
                event_ingest_binding = '{{
                  "source": "pytest-line",
                  "org_key": "org-a",
                  "event_types": ["device.line.reading.v1"]
                }}'::jsonb
            WHERE id = {self.worker_id};
            """,
        )
        opened = self.db.worker_open_session(self.identity, "127.0.0.1")
        self.session = str(opened["session_token"])
        self.auth = WorkerCallAuth(
            worker_id=self.worker_id,
            session_token=self.session,
            identity_token=self.identity,
            client_ip="127.0.0.1",
        )
        self._delete_if_exists("AdapterInheritWait")
        self._delete_if_exists("AdapterInheritSchedule")

    def tearDown(self) -> None:
        self.db.close()

    def _delete_if_exists(self, name: str) -> None:
        try:
            self.db.delete_workflow_definition(name, delete_instances=True)
        except Exception:
            pass

    def _deploy_wait_workflow(self) -> int:
        spec = {
            "name": "AdapterInheritWait",
            "root_node_key": "root",
            "nodes": [
                {
                    "node_key": "root",
                    "node_type": "SEQUENCE",
                },
                {
                    "node_key": "cor_wait",
                    "node_type": "WAIT_EVENT",
                    "wait_event_type": "device.line.reading.v1",
                },
            ],
            "edges": [
                {"parent_node_key": "root", "child_node_key": "cor_wait", "child_order": 0, "branch_kind": "SEQUENCE"},
            ],
            "event_triggers": [
                {
                    "event": "device.line.reading.v1",
                    "mode": "start_or_signal",
                    "filter_json": {"device_key": "line-1"},
                },
            ],
        }
        created = self.db.create_workflow_definition(spec)
        return int(created["workflow_version_id"])

    def _deploy_schedule_workflow(self) -> int:
        self.db.upsert_workflow_action(
            "workflow.device_adapter.observe",
            "device.adapter",
            execution_mode="in_process",
            in_process_handler="goliath_app.device_adapter.command_handler:handle_device_adapter_observe",
            exclusive_worker=True,
        )
        spec = {
            "name": "AdapterInheritSchedule",
            "root_node_key": "tick_root",
            "nodes": [
                {
                    "node_key": "tick_root",
                    "node_type": "SCHEDULE",
                    "schedule_interval_seconds": 2,
                },
                {
                    "node_key": "observe_tick",
                    "node_type": "ACTION",
                    "action_name": "workflow.device_adapter.observe",
                    "input_template": {
                        "observe_key": "scheduled_observe",
                        "context": {"organization_key": "org-a"},
                    },
                },
            ],
            "edges": [
                {
                    "parent_node_key": "tick_root",
                    "child_node_key": "observe_tick",
                    "child_order": 0,
                    "branch_kind": "SEQUENCE",
                },
            ],
        }
        created = self.db.create_workflow_definition(spec)
        return int(created["workflow_version_id"])

    def test_cross_tenant_rejected_when_binding_fixes_org(self) -> None:
        from rest.db.base import EventIngestForbidden

        with self.assertRaises(EventIngestForbidden) as ctx:
            self.db.ingest_event_worker(
                self.auth,
                event_type="device.line.reading.v1",
                source="pytest-line",
                idempotency_key="cross-tenant-1",
                payload_json={"organization_key": "org-b", "device_key": "line-1"},
            )
        self.assertIn("source/org/device/event_type mismatch", str(ctx.exception))

    def test_event_wakes_wait_and_api_key_ingest(self) -> None:
        wv = self._deploy_wait_workflow()
        inst = self.db.create_workflow_instance(wv, {})
        self.db.start_workflow_instance(inst)

        self.db.ingest_event_worker(
            self.auth,
            event_type="device.line.reading.v1",
            source="pytest-line",
            idempotency_key="reading-1",
            payload_json={"organization_key": "org-a", "device_key": "line-1"},
        )

        row = _psql_query(
            self.dsn,
            f"""
            SELECT ne.status FROM wf.node_execution ne
            INNER JOIN wf.workflow_node wn ON wn.id = ne.workflow_node_id
            WHERE ne.workflow_instance_id = {inst} AND wn.node_key = 'cor_wait';
            """,
        )
        self.assertEqual(row, "SUCCEEDED")

        key_plain = "k-test-ingest-ada"
        digest = _digest_api_key(key_plain)
        _psql_query(
            self.dsn,
            f"""
            INSERT INTO wf.event_ingest_api_key (key_hash, label, allowed_org_keys, allowed_sources, allowed_event_types)
            VALUES (decode('{digest}','hex'), 'pytest', '["org-a"]'::jsonb, '["pytest-portal"]'::jsonb, '["device.portal.ping.v1"]'::jsonb);
            """,
        )
        def _cleanup_key() -> None:
            subprocess.run(
                ["psql", "-q", "-v", "ON_ERROR_STOP=1", self.dsn, "-c", f"DELETE FROM wf.event_ingest_api_key WHERE key_hash = decode('{digest}','hex');"],
                env=_pg_env(),
                capture_output=True,
                check=False,
            )

        self.addCleanup(_cleanup_key)

        out = self.db.ingest_event_with_api_key(
            digest,
            event_type="device.portal.ping.v1",
            source="pytest-portal",
            idempotency_key="portal-1",
            payload_json={"organization_key": "org-a"},
        )
        self.assertFalse(out.get("duplicate", True))

        with self.assertRaises(EventIngestForbidden):
            self.db.ingest_event_with_api_key(
                digest,
                event_type="device.portal.ping.v1",
                source="pytest-portal",
                idempotency_key="portal-2",
                payload_json={"organization_key": "org-z"},
            )

    def test_schedule_claim_observe_exclusive(self) -> None:
        wv = self._deploy_schedule_workflow()
        inst = self.db.create_workflow_instance(wv, {})
        self.db.start_workflow_instance(inst)

        _psql_query(
            self.dsn,
            f"""
            UPDATE wf.node_execution
            SET available_at_utc = (now() AT TIME ZONE 'utc') - interval '5 seconds'
            WHERE workflow_instance_id = {inst} AND status = 'READY';
            """,
        )

        claimed = self.db.worker_request_task(self.auth, "device.adapter", 120)
        self.assertTrue(claimed.get("has_task"), claimed)
        self.assertEqual(str(claimed.get("action_name")), "workflow.device_adapter.observe")

        ne_id = int(claimed["node_execution_id"])
        self.db.worker_submit_result(
            ne_id,
            self.auth,
            0,
            {"readings": [{"value": 1}], "simulated": True},
        )

        _psql_query(
            self.dsn,
            f"""
            UPDATE wf.node_execution
            SET available_at_utc = (now() AT TIME ZONE 'utc') - interval '1 seconds'
            WHERE workflow_instance_id = {inst} AND status = 'READY';
            """,
        )

        claimed2 = self.db.worker_request_task(self.auth, "device.adapter", 120)
        self.assertTrue(claimed2.get("has_task"), claimed2)


if __name__ == "__main__":
    unittest.main()
