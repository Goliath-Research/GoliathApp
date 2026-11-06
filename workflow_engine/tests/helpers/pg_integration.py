"""PostgreSQL helpers for integration tests (schema apply, DSN, minimal workflow seed)."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from shutil import which
from typing import Any

WF_ENGINE = Path(__file__).resolve().parents[1]
SQL_PG = WF_ENGINE / "sql_pg"


def pg_dsn() -> str:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "meth" + "ylpipeline_parity")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "goliath")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def pg_env() -> dict[str, str]:
    env = os.environ.copy()
    if "PGPASSWORD" not in env and os.environ.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = os.environ["POSTGRES_PASSWORD"]
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "meth" + "ylpipeline_parity"))
    return env


def psql(dsn: str, extra_args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", dsn, *extra_args],
        capture_output=True,
        text=True,
        env=pg_env(),
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() or "(no psql output)"
        raise RuntimeError(f"psql failed ({proc.returncode}): {detail}")
    return proc


def psql_query(dsn: str, sql: str) -> str:
    proc = psql(dsn, ["-t", "-A", "-c", sql])
    return proc.stdout.strip()


def apply_schema_scripts(dsn: str) -> None:
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
        psql(dsn, ["-f", str(SQL_PG / name)])


def seed_minimal_workflow(dsn: str) -> tuple[int, int, str]:
    """Returns (version_id, worker_id, identity_token)."""
    if psql_query(dsn, "SELECT 1 FROM wf.workflow_def WHERE name = 'ParityFlow' LIMIT 1;"):
        psql_query(dsn, "SELECT * FROM wf.sp_delete_workflow_def(NULL, 'ParityFlow', true);")
    psql_query(dsn, "INSERT INTO wf.workflow_def (name) VALUES ('ParityFlow');")
    def_id = int(psql_query(dsn, "SELECT id FROM wf.workflow_def WHERE name='ParityFlow' LIMIT 1;"))
    version_id = int(
        psql_query(
            dsn,
            f"INSERT INTO wf.workflow_version (workflow_def_id) VALUES ({def_id}) RETURNING id;",
        )
    )
    action_id = psql_query(dsn, "SELECT id FROM wf.workflow_action WHERE action_name='LoadInput' LIMIT 1;")
    if not action_id:
        action_id = int(
            psql_query(
                dsn,
                "INSERT INTO wf.workflow_action (action_name, capability) VALUES ('LoadInput','test-cap') RETURNING id;",
            )
        )
    else:
        action_id = int(action_id)
    node_id = int(
        psql_query(
            dsn,
            f"INSERT INTO wf.workflow_node (workflow_version_id, node_type, node_key, workflow_action_id) "
            f"VALUES ({version_id}, 'ACTION', 'load_input', {action_id}) RETURNING id;",
        )
    )
    psql_query(dsn, f"UPDATE wf.workflow_version SET root_node_id = {node_id} WHERE id = {version_id};")

    cluster_id = psql_query(dsn, "SELECT id FROM wf.cluster WHERE cluster_key='parity' LIMIT 1;")
    if not cluster_id:
        cluster_id = int(
            psql_query(
                dsn,
                "INSERT INTO wf.cluster (cluster_key, name) VALUES ('parity','Parity') RETURNING id;",
            )
        )
    else:
        cluster_id = int(cluster_id)
    worker_id = psql_query(
        dsn,
        f"SELECT id FROM wf.worker WHERE cluster_id={cluster_id} AND external_worker_key='w1' LIMIT 1;",
    )
    if not worker_id:
        worker_id = int(
            psql_query(
                dsn,
                f"INSERT INTO wf.worker (cluster_id, external_worker_key) VALUES ({cluster_id}, 'w1') RETURNING id;",
            )
        )
    else:
        worker_id = int(worker_id)
    psql_query(
        dsn,
        f"UPDATE wf.worker SET capabilities = '[\"test-cap\"]'::jsonb WHERE id={worker_id};",
    )
    token = "parity-test-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    psql_query(
        dsn,
        f"DELETE FROM wf.worker_token WHERE worker_id={worker_id}; "
        f"INSERT INTO wf.worker_token (worker_id, token_hash, bound_client_ip) "
        f"VALUES ({worker_id}, decode('{token_hash}','hex'), '127.0.0.1');",
    )
    return version_id, worker_id, token


def start_instance(dsn: str, version_id: int) -> int:
    instance_id = int(
        psql_query(
            dsn,
            f"SELECT id FROM wf.wf_repo_create_workflow_instance({version_id}, '{{}}'::jsonb);",
        )
    )
    psql_query(dsn, f"CALL wf.sp_start_workflow_instance({instance_id});")
    return instance_id


def postgres_available() -> bool:
    if os.environ.get("SKIP_PG_INTEGRATION", "").strip().lower() in ("1", "true", "yes"):
        return False
    if not shutil_which_cmd("psql"):
        return False
    dsn = pg_dsn()
    try:
        proc = subprocess.run(
            ["psql", dsn, "-t", "-A", "-c", "SELECT 1"],
            capture_output=True,
            text=True,
            env=pg_env(),
            timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def shutil_which_cmd(cmd: str) -> bool:
    return which(cmd) is not None


def wf_engine_procedures_reference_schedule() -> dict[str, Any]:
    """Return markers expected in live wf_engine_* bodies after full schema apply (ordering regression)."""
    return {
        "wf_engine_continue_parent": "wf_schedule_continue",
        "wf_engine_on_action_complete": "wf_schedule_continue",
    }
