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


def _pg_dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "methylpipeline_parity")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "methyl")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    if "PGPASSWORD" not in env and os.environ.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = os.environ["POSTGRES_PASSWORD"]
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "methylpipeline_parity"))
    return env


def _psql(dsn: str, extra_args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", dsn, *extra_args],
        capture_output=True,
        text=True,
        env=_pg_env(),
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or "(no psql output)"
        raise RuntimeError(f"psql failed ({proc.returncode}): {detail}")
    return proc


def _psql_query(dsn: str, sql: str) -> str:
    proc = _psql(dsn, ["-t", "-A", "-c", sql])
    return proc.stdout.strip()


def _apply_schema_scripts(dsn: str) -> None:
    text = (SQL_PG / "apply_schema.sh").read_text(encoding="utf-8")
    marker = "SCRIPTS=("
    start = text.find(marker)
    if start < 0:
        raise ValueError("No SCRIPTS=( in apply_schema.sh")
    names: list[str] = []
    for line in text[start + len(marker) :].splitlines():
        stripped = line.strip()
        if stripped.startswith(")"):
            break
        if not stripped or stripped.startswith("#"):
            continue
        token = stripped.split("#", 1)[0].strip().rstrip("\\").strip()
        if token:
            names.append(token)
    for name in names:
        _psql(dsn, ["-f", str(SQL_PG / name)])


def seed_minimal_workflow(dsn: str) -> tuple[int, int, str]:
    """Returns (version_id, worker_id, identity_token)."""
    if _psql_query(dsn, "SELECT 1 FROM wf.workflow_def WHERE name = 'ParityFlow' LIMIT 1;"):
        _psql_query(dsn, "SELECT * FROM wf.sp_delete_workflow_def(NULL, 'ParityFlow', true);")
    _psql_query(dsn, "INSERT INTO wf.workflow_def (name) VALUES ('ParityFlow');")
    def_id = int(_psql_query(dsn, "SELECT id FROM wf.workflow_def WHERE name='ParityFlow' LIMIT 1;"))
    version_id = int(
        _psql_query(
            dsn,
            f"INSERT INTO wf.workflow_version (workflow_def_id) VALUES ({def_id}) RETURNING id;",
        )
    )
    action_id = _psql_query(dsn, "SELECT id FROM wf.workflow_action WHERE action_name='LoadInput' LIMIT 1;")
    if not action_id:
        action_id = int(
            _psql_query(
                dsn,
                "INSERT INTO wf.workflow_action (action_name, capability) VALUES ('LoadInput','test-cap') RETURNING id;",
            )
        )
    else:
        action_id = int(action_id)
    node_id = int(
        _psql_query(
            dsn,
            f"INSERT INTO wf.workflow_node (workflow_version_id, node_type, node_key, workflow_action_id) "
            f"VALUES ({version_id}, 'ACTION', 'load_input', {action_id}) RETURNING id;",
        )
    )
    _psql_query(dsn, f"UPDATE wf.workflow_version SET root_node_id = {node_id} WHERE id = {version_id};")

    cluster_id = _psql_query(dsn, "SELECT id FROM wf.cluster WHERE cluster_key='parity' LIMIT 1;")
    if not cluster_id:
        cluster_id = int(
            _psql_query(
                dsn,
                "INSERT INTO wf.cluster (cluster_key, name) VALUES ('parity','Parity') RETURNING id;",
            )
        )
    else:
        cluster_id = int(cluster_id)
    worker_id = _psql_query(
        dsn,
        f"SELECT id FROM wf.worker WHERE cluster_id={cluster_id} AND external_worker_key='w1' LIMIT 1;",
    )
    if not worker_id:
        worker_id = int(
            _psql_query(
                dsn,
                f"INSERT INTO wf.worker (cluster_id, external_worker_key) VALUES ({cluster_id}, 'w1') RETURNING id;",
            )
        )
    else:
        worker_id = int(worker_id)
    _psql_query(
        dsn,
        f"UPDATE wf.worker SET capabilities = '[\"test-cap\"]'::jsonb WHERE id={worker_id};",
    )
    token = "parity-test-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    _psql_query(
        dsn,
        f"DELETE FROM wf.worker_token WHERE worker_id={worker_id}; "
        f"INSERT INTO wf.worker_token (worker_id, token_hash, bound_client_ip) "
        f"VALUES ({worker_id}, decode('{token_hash}','hex'), '127.0.0.1');",
    )
    return version_id, worker_id, token


def start_instance(dsn: str, version_id: int) -> int:
    instance_id = int(
        _psql_query(
            dsn,
            f"SELECT id FROM wf.wf_repo_create_workflow_instance({version_id}, '{{}}'::jsonb);",
        )
    )
    _psql_query(dsn, f"CALL wf.sp_start_workflow_instance({instance_id});")
    return instance_id


def _postgres_available() -> bool:
    if os.environ.get("SKIP_PG_INTEGRATION", "").strip().lower() in ("1", "true", "yes"):
        return False
    if not shutil_which("psql"):
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


def shutil_which(cmd: str) -> bool:
    from shutil import which

    return which(cmd) is not None


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
