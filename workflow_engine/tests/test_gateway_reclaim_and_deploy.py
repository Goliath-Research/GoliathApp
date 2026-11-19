"""goliath-reclaim-leases and non-destructive graph deploy, owned by the gateway package.

Neither path may import an ``ops`` package: a descendant must not have to overlay one.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SQL_PG = ROOT / "sql_pg"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    return env


def _psql(sql: str, env: dict[str, str]) -> str:
    proc = subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
        env=env, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def test_entry_point_is_owned_by_gateway() -> None:
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts["goliath-reclaim-leases"] == "rest.reclaim_leases:main"
    for module in ("rest/reclaim_leases.py", "cfg/publish_program.py", "cfg/cli.py"):
        text = (ROOT / module).read_text()
        assert "from ops" not in text and "import ops" not in text, module


def test_reclaim_cli_uses_db(capsys: pytest.CaptureFixture[str]) -> None:
    from rest import reclaim_leases

    calls: list[tuple[object, int]] = []

    class FakeDb:
        def reclaim_expired_leases(self, *, workflow_instance_id=None, grace_seconds=60):
            calls.append((workflow_instance_id, grace_seconds))
            return [{"node_execution_id": 7, "workflow_instance_id": 3, "previous_worker_id": 1}]

    rows = reclaim_leases.reclaim_expired_leases(grace_seconds=30, db=FakeDb())
    assert rows[0]["node_execution_id"] == 7 and calls == [(None, 30)]


@pytest.fixture(scope="module")
def pg_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(SQL_PG / "apply_schema.sh")], env=env, check=True)
    return env


def _conninfo(env: dict[str, str]) -> str:
    return (
        f"postgresql://{env['PGUSER']}:{env['PGPASSWORD']}@{env['PGHOST']}:{env['PGPORT']}/"
        f"{env['PGDATABASE']}"
    )


def test_reclaim_and_deploy_against_postgres(pg_env: dict[str, str]) -> None:
    from rest.connection import resolve_connection_config
    from rest.db import open_gateway_db

    db = open_gateway_db(resolve_connection_config(connection_string=_conninfo(pg_env)))
    try:
        assert isinstance(db.reclaim_expired_leases(grace_seconds=60), list)

        suffix = uuid.uuid4().hex[:6]
        action = f"deploy_action_{suffix}"
        _psql(f"CALL wf.wf_repo_upsert_workflow_action('{action}', 'cpu')", pg_env)
        spec = {
            "name": f"deploy-graph-{suffix}",
            "root_node_key": "root",
            "nodes": [
                {"node_key": "root", "node_type": "SEQUENCE"},
                {"node_key": "step", "node_type": "ACTION", "action_name": action},
            ],
            "edges": [{"parent_node_key": "root", "child_node_key": "step", "child_order": 0}],
        }
        first = db.deploy_workflow_graph(spec, activate=True)
        assert first["created_definition"] is True
        # A run on the first version must survive the redeploy.
        instance_id = int(_psql(
            f"INSERT INTO wf.workflow_instance (workflow_version_id, status, context_json) "
            f"VALUES ({first['workflow_version_id']}, 'COMPLETED', '{{}}'::jsonb) RETURNING id",
            pg_env,
        ))
        staged = db.deploy_workflow_graph(spec, activate=False)
        assert staged["created_definition"] is False
        assert staged["workflow_def_id"] == first["workflow_def_id"]
        rows = _psql(
            "SELECT string_agg(version_minor || ':' || is_active, ',' ORDER BY version_minor) "
            f"FROM wf.workflow_version WHERE workflow_def_id = {first['workflow_def_id']}",
            pg_env,
        )
        assert rows == "0:true,1:false"
        activated = db.deploy_workflow_graph(spec, activate=True)
        rows = _psql(
            "SELECT string_agg(version_minor || ':' || is_active, ',' ORDER BY version_minor) "
            f"FROM wf.workflow_version WHERE workflow_def_id = {first['workflow_def_id']}",
            pg_env,
        )
        assert rows == "0:false,1:false,2:true"
        assert activated["workflow_version_id"] != first["workflow_version_id"]
        assert _psql(f"SELECT count(*) FROM wf.workflow_instance WHERE id = {instance_id}", pg_env) == "1"
        assert _psql(f"SELECT count(*) FROM wf.workflow_def WHERE name = '{spec['name']}'", pg_env) == "1"
    finally:
        db.close()
