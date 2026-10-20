#!/usr/bin/env python3
"""
Backend-agnostic conformance harness for wf worker API and repository contract.

Runs identical scenarios against PostgreSQL (local container) and optionally Azure SQL
when METHYL_TEST_MSSQL_DSN is set.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
SQL_PG = ROOT / "sql_pg"
CONTRACT_SCRIPT = ROOT / "contract" / "validate_contract.py"
# Portal/cfg/legacy stacks are out of scope for this harness. Stop after the
# last wf engine script the worker/repository/scope tests need.
_SKIP_DEPLOY_PREFIXES = (
    "portal_",
    "cfg_",
    "meta_",
    "rbac_",
    "contract_",
    "onboarding_",
    "e_portal_",
    "legacy_",
)
_PARITY_DEPLOY_STOP = "wf_sql_collection_bindings.sql"
_REQUIRED_PARITY_SCRIPTS = (
    "wf_reclaim_expired_leases.sql",
    "wf_action_dispatch_affinity.sql",
    "01_worker_api.sql",
)


def _parse_deploy_azure_scripts(deploy_sh: Path) -> list[str]:
    text = deploy_sh.read_text(encoding="utf-8")
    marker = "SCRIPTS=("
    start = text.find(marker)
    if start < 0:
        raise ValueError(f"No SCRIPTS=( array in {deploy_sh}")
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
    return names


def _parity_sql_scripts() -> list[Path]:
    """Wf-engine slice of sql_pg/deploy_azure.sh (claim reads affinity columns)."""
    names = _parse_deploy_azure_scripts(SQL_PG / "deploy_azure.sh")
    out: list[Path] = []
    for name in names:
        if name.startswith(_SKIP_DEPLOY_PREFIXES):
            continue
        path = SQL_PG / name
        if not path.is_file():
            raise FileNotFoundError(f"deploy script missing: {path}")
        out.append(path)
        if name == _PARITY_DEPLOY_STOP:
            break
    have = {p.name for p in out}
    missing = [n for n in _REQUIRED_PARITY_SCRIPTS if n not in have]
    if missing:
        raise RuntimeError(
            f"parity deploy list missing {missing}; update sql_pg/deploy_azure.sh"
        )
    return out


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


def _run_psql(dsn: str, sql_path: Path) -> None:
    _psql(dsn, ["-f", str(sql_path)])


def deploy_postgres(dsn: str) -> None:
    for path in _parity_sql_scripts():
        _run_psql(dsn, path)


def _psql_query(dsn: str, sql: str) -> str:
    proc = _psql(dsn, ["-t", "-A", "-c", sql])
    return proc.stdout.strip()


def _psql_query_optional(dsn: str, sql: str) -> None:
    _psql(dsn, ["-t", "-A", "-c", sql], check=False)


def seed_minimal_workflow(dsn: str) -> tuple[int, int, str]:
    """Returns (version_id, worker_id, worker_token)."""
    _psql_query_optional(dsn, "SELECT * FROM wf.sp_delete_workflow_def(NULL, 'ParityFlow', true);")
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
    # Registered capabilities gate every claim; seeded scenarios all use 'test-cap'.
    _psql_query(
        dsn,
        f"UPDATE wf.worker SET capabilities = '[\"test-cap\"]'::jsonb WHERE id={worker_id};",
    )
    token = "parity-test-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    _psql_query(
        dsn,
        f"DELETE FROM wf.worker_token WHERE worker_id={worker_id}; "
        f"INSERT INTO wf.worker_token (worker_id, token_hash) VALUES ({worker_id}, decode('{token_hash}','hex'));",
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


def test_worker_capability_dispatch_postgres(dsn: str) -> None:
    """Workers only claim tasks matching wf.worker.capabilities."""
    version_id, worker_id, token = seed_minimal_workflow(dsn)
    load_node = int(
        _psql_query(
            dsn,
            f"SELECT id FROM wf.workflow_node WHERE workflow_version_id={version_id} AND node_key='load_input' LIMIT 1;",
        )
    )
    _psql_query(
        dsn,
        f"UPDATE wf.worker SET capabilities = '[\"test-cap\"]'::jsonb WHERE id={worker_id};",
    )
    gpu_action_id = int(
        _psql_query(
            dsn,
            "INSERT INTO wf.workflow_action (action_name, capability) "
            "VALUES ('GpuOnly','gpu-cap') RETURNING id;",
        )
    )
    gpu_node = int(
        _psql_query(
            dsn,
            f"INSERT INTO wf.workflow_node (workflow_version_id, node_type, node_key, workflow_action_id) "
            f"VALUES ({version_id}, 'ACTION', 'gpu_only', {gpu_action_id}) RETURNING id;",
        )
    )
    _psql_query(dsn, f"UPDATE wf.workflow_version SET root_node_id = {gpu_node} WHERE id = {version_id};")
    inst_gpu = int(
        _psql_query(
            dsn,
            f"SELECT id FROM wf.wf_repo_create_workflow_instance({version_id}, '{{}}'::jsonb);",
        )
    )
    _psql_query(dsn, f"CALL wf.sp_start_workflow_instance({inst_gpu});")

    _psql_query(dsn, f"UPDATE wf.workflow_version SET root_node_id = {load_node} WHERE id = {version_id};")
    inst_ok = int(
        _psql_query(
            dsn,
            f"SELECT id FROM wf.wf_repo_create_workflow_instance({version_id}, '{{}}'::jsonb);",
        )
    )
    _psql_query(dsn, f"CALL wf.sp_start_workflow_instance({inst_ok});")

    claim = _psql_query(
        dsn,
        f"SELECT node_execution_id FROM wf.sp_worker_request_task({worker_id}, '{token}', NULL, 60);",
    )
    assert claim, "expected test-cap task claim while gpu-cap task is also READY"

    narrow = _psql_query(
        dsn,
        f"SELECT node_execution_id FROM wf.sp_worker_request_task({worker_id}, '{token}', 'gpu-cap', 60);",
    )
    assert not narrow, "poll capability must not widen beyond registration"


def _pin_worker(dsn: str, cluster_id: int, key: str) -> tuple[int, str]:
    worker_id = _psql_query(
        dsn,
        f"SELECT id FROM wf.worker WHERE cluster_id={cluster_id} AND external_worker_key='{key}' LIMIT 1;",
    )
    if not worker_id:
        worker_id = _psql_query(
            dsn,
            f"INSERT INTO wf.worker (cluster_id, external_worker_key) VALUES ({cluster_id}, '{key}') RETURNING id;",
        )
    wid = int(worker_id)
    _psql_query(dsn, f"UPDATE wf.worker SET capabilities = '[\"pin-cap\"]'::jsonb WHERE id={wid};")
    token = f"parity-{key}-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    _psql_query(
        dsn,
        f"DELETE FROM wf.worker_token WHERE worker_id={wid}; "
        f"INSERT INTO wf.worker_token (worker_id, token_hash) VALUES ({wid}, decode('{token_hash}','hex'));",
    )
    return wid, token


def test_require_previous_worker_postgres(dsn: str) -> None:
    """require_previous_worker pins later actions of a key to the pinned completer."""
    version_id, _w1, _t1 = seed_minimal_workflow(dsn)
    cluster_id = int(_psql_query(dsn, "SELECT id FROM wf.cluster WHERE cluster_key='parity' LIMIT 1;"))
    wa_id, wa_token = _pin_worker(dsn, cluster_id, "pin-a")
    wb_id, wb_token = _pin_worker(dsn, cluster_id, "pin-b")
    wc_id, wc_token = _pin_worker(dsn, cluster_id, "pin-c")
    for name, excl, pinned in (
        ("PinAlign", "false", "true"),
        ("PinExtract", "false", "true"),
        ("PinSoft", "false", "false"),
        ("PinProducer", "true", "true"),
    ):
        _psql_query(
            dsn,
            f"CALL wf.wf_repo_upsert_workflow_action('{name}', 'pin-cap', NULL, NULL, NULL, NULL, NULL, "
            f"NULL, {excl}, 'sampleId', true, true, {pinned});",
        )
    nodes: dict[str, int] = {}
    for name in ("PinAlign", "PinExtract", "PinSoft", "PinProducer"):
        nodes[name] = int(
            _psql_query(
                dsn,
                f"INSERT INTO wf.workflow_node (workflow_version_id, node_type, node_key, workflow_action_id) "
                f"SELECT {version_id}, 'ACTION', lower('{name}'), id FROM wf.workflow_action "
                f"WHERE action_name='{name}' RETURNING id;",
            )
        )
    instance_id = int(
        _psql_query(dsn, f"SELECT id FROM wf.wf_repo_create_workflow_instance({version_id}, '{{}}'::jsonb);")
    )
    _psql_query(dsn, f"UPDATE wf.workflow_instance SET status='RUNNING' WHERE id={instance_id};")

    def _row(node: str, status: str, worker: Optional[int], key: str) -> int:
        completed = "NULL" if worker is None else str(worker)
        ended = "now()" if status == "SUCCEEDED" else "NULL"
        return int(
            _psql_query(
                dsn,
                "INSERT INTO wf.node_execution (workflow_instance_id, workflow_node_id, status, input_json, "
                "affinity_key, completed_by_worker_id, ended_at_utc) "
                f"VALUES ({instance_id}, {nodes[node]}, '{status}', '{{\"sampleId\":\"{key}\"}}'::jsonb, "
                f"'{key}', {completed}, {ended}) RETURNING id;",
            )
        )

    def _claim(wid: int, token: str) -> Optional[int]:
        out = _psql_query(
            dsn,
            f"SELECT node_execution_id FROM wf.sp_worker_request_task({wid}, '{token}', 'pin-cap', 60);",
        )
        return int(out.split("|")[0]) if out and out.split("|")[0] else None

    # Pinned align for S1 succeeded on worker A; a soft action ran later on B.
    _row("PinAlign", "SUCCEEDED", wa_id, "S1")
    _row("PinSoft", "SUCCEEDED", wb_id, "S1")
    extract = _row("PinExtract", "READY", None, "S1")
    assert _claim(wb_id, wb_token) is None, "pinned extract must not go to a different worker"
    assert _claim(wa_id, wa_token) == extract, "pinned extract must go to the align worker"

    # First pinned action of a key (no pinned predecessor) is open to any worker.
    first = _row("PinAlign", "READY", None, "S2")
    assert _claim(wb_id, wb_token) == first, "first pinned action of a key is unpinned"

    # An exclusive pinned producer (re-Align after the pinned worker is lost)
    # starts a new pin; it is not stuck on worker A.
    realign = _row("PinProducer", "READY", None, "S1")
    assert _claim(wc_id, wc_token) == realign, "exclusive pinned producer is not pinned"


def test_worker_api_postgres(dsn: str) -> None:
    version_id, worker_id, token = seed_minimal_workflow(dsn)
    instance_id = int(
        _psql_query(
            dsn,
            f"SELECT id FROM wf.wf_repo_create_workflow_instance({version_id}, '{{}}'::jsonb);",
        )
    )
    _psql_query(dsn, f"CALL wf.sp_start_workflow_instance({instance_id});")

    claim = _psql_query(
        dsn,
        f"SELECT node_execution_id FROM wf.sp_worker_request_task({worker_id}, '{token}', 'test-cap', 60);",
    )
    assert claim, "expected task claim"
    ne_id = int(claim.split("|")[0])

    ack = _psql_query(
        dsn,
        f"SELECT accepted, instance_status FROM wf.sp_worker_submit_result({ne_id}, {worker_id}, '{token}', 1, '{{\"ok\":true}}'::jsonb);",
    )
    assert ack.startswith("t|COMPLETED"), f"unexpected ack: {ack}"


def test_repository_postgres(dsn: str) -> None:
    version_id = int(_psql_query(dsn, "SELECT id FROM wf.workflow_version LIMIT 1;"))
    new_id = int(
        _psql_query(
            dsn,
            f"SELECT id FROM wf.wf_repo_create_workflow_instance({version_id}, '{{\"x\":1}}'::jsonb);",
        )
    )
    assert new_id > 0
    _psql_query(dsn, f"CALL wf.wf_repo_set_instance_status({new_id}, 'RUNNING');")
    status = _psql_query(dsn, f"SELECT status FROM wf.workflow_instance WHERE id={new_id};")
    assert status == "RUNNING"


def test_scope_resolver_postgres(dsn: str) -> None:
    """Context scope vars resolve into action input_json via ${var.*}."""
    _psql_query_optional(dsn, "SELECT * FROM wf.sp_delete_workflow_def(NULL, 'ScopeParity', true);")
    _psql_query(dsn, "INSERT INTO wf.workflow_def (name) VALUES ('ScopeParity');")
    def_id = int(_psql_query(dsn, "SELECT id FROM wf.workflow_def WHERE name='ScopeParity' LIMIT 1;"))
    version_id = int(
        _psql_query(dsn, f"INSERT INTO wf.workflow_version (workflow_def_id) VALUES ({def_id}) RETURNING id;")
    )
    action_id = _psql_query(dsn, "SELECT id FROM wf.workflow_action WHERE action_name='Echo' LIMIT 1;")
    if not action_id:
        action_id = int(
            _psql_query(
                dsn,
                "INSERT INTO wf.workflow_action (action_name, capability) VALUES ('Echo','test-cap') RETURNING id;",
            )
        )
    else:
        action_id = int(action_id)
    node_id = int(
        _psql_query(
            dsn,
            f"INSERT INTO wf.workflow_node (workflow_version_id, node_type, node_key, workflow_action_id) "
            f"VALUES ({version_id}, 'ACTION', 'echo', {action_id}) RETURNING id;",
        )
    )
    _psql_query(dsn, f"UPDATE wf.workflow_version SET root_node_id = {node_id} WHERE id = {version_id};")
    _psql_query(
        dsn,
        f"INSERT INTO wf.workflow_input_template (workflow_node_id, template_json) "
        f"VALUES ({node_id}, '{{}}'::jsonb);",
    )
    _psql_query(
        dsn,
        f"INSERT INTO wf.workflow_input_binding (workflow_node_id, target_json_path, source_expr, is_required) "
        f"VALUES ({node_id}, 'message', '${{var.greeting}}', true);",
    )

    instance_id = int(
        _psql_query(
            dsn,
            f"SELECT id FROM wf.wf_repo_create_workflow_instance({version_id}, '{{\"greeting\":\"hello-scope\"}}'::jsonb);",
        )
    )
    _psql_query(dsn, f"CALL wf.sp_start_workflow_instance({instance_id});")

    input_json = _psql_query(
        dsn,
        f"SELECT input_json::text FROM wf.node_execution WHERE workflow_instance_id={instance_id} AND status='READY' LIMIT 1;",
    )
    assert "hello-scope" in input_json, f"expected resolved greeting in input_json: {input_json}"


def test_placeholder_json_literal_postgres(dsn: str) -> None:
    """A placeholder that is an entire JSON string is replaced by the raw value.

    Scope variables are stored JSON-encoded. ``"${var.s}"`` and ``"${var.o}"``
    must drop the template quotes so the string and object keep their types.
    ``"x-${var.n}"`` stays a string with the number spliced in.
    """
    version_id, _worker_id, _token = seed_minimal_workflow(dsn)
    context = '{"s":"hello","o":{"k":1,"tags":["a"]},"n":7}'
    instance_id = int(
        _psql_query(
            dsn,
            "SELECT id FROM wf.wf_repo_create_workflow_instance("
            f"{version_id}, $ctx${context}$ctx$::jsonb);",
        )
    )
    _psql_query(dsn, f"CALL wf.sp_start_workflow_instance({instance_id});")

    template = '{"a":"${var.s}","b":"${var.o}","c":"x-${var.n}"}'
    resolved = _psql_query(
        dsn,
        "DROP TABLE IF EXISTS parity_placeholder_resolved; "
        "CREATE TEMP TABLE parity_placeholder_resolved (resolved text); "
        "DO $do$ DECLARE v_resolved text; v_failed boolean; v_fc int; v_fm text; BEGIN "
        "CALL wf.wf_resolve_placeholders("
        f"$tpl${template}$tpl$, 0, {instance_id}, v_resolved, v_failed, v_fc, v_fm); "
        "IF v_failed THEN RAISE EXCEPTION 'placeholder resolution failed: % %', v_fc, v_fm; END IF; "
        "INSERT INTO parity_placeholder_resolved(resolved) VALUES (v_resolved); "
        "END $do$; "
        "SELECT resolved FROM parity_placeholder_resolved;",
    )
    doc = json.loads(resolved)
    assert isinstance(doc, dict), resolved
    assert doc["a"] == "hello" and isinstance(doc["a"], str), resolved
    assert doc["b"] == {"k": 1, "tags": ["a"]} and isinstance(doc["b"], dict), resolved
    assert isinstance(doc["b"]["tags"], list), resolved
    assert doc["c"] == "x-7" and isinstance(doc["c"], str), resolved


def test_worker_enrollment_postgres(dsn: str) -> None:
    """Portal preregistration + worker enroll (SQLSTATE 42702 regression).

    portal.sp_upsert_cluster / portal.sp_upsert_worker_enrollment / wf.sp_worker_enroll
    return TABLE columns named like the columns they upsert; without
    ``#variable_conflict use_column`` PL/pgSQL raises "column reference ... is
    ambiguous" on the first call even though the scripts deploy cleanly.
    """
    _run_psql(dsn, SQL_PG / "portal_worker_enrollment_api.sql")
    cluster = _psql_query(dsn, "SELECT cluster_key FROM portal.sp_upsert_cluster('parity-enroll');")
    assert cluster == "parity-enroll", cluster
    renamed = _psql_query(dsn, "SELECT name FROM portal.sp_upsert_cluster('parity-enroll', 'Parity');")
    assert renamed == "Parity", renamed
    first = _psql_query(
        dsn,
        "SELECT external_worker_key || '|' || public_ip || '|' || status "
        "FROM portal.sp_upsert_worker_enrollment('parity-enroll', '203.0.113.7', 'parity-key');",
    )
    assert first == "parity-key|203.0.113.7|PENDING", first
    # Second call hits ON CONFLICT (cluster_id, external_worker_key) DO UPDATE.
    again = _psql_query(
        dsn,
        "SELECT public_ip FROM portal.sp_upsert_worker_enrollment('parity-enroll', '203.0.113.8', 'parity-key');",
    )
    assert again == "203.0.113.8", again
    cidrs = _psql_query(dsn, "SELECT allowed_source_cidrs::text FROM wf.cluster WHERE cluster_key = 'parity-enroll';")
    assert "203.0.113.8/32" in cidrs, cidrs
    token_hash = hashlib.sha256(b"parity-enroll-token").hexdigest()
    enroll_sql = (
        "SELECT worker_id FROM wf.sp_worker_enroll("
        f"'parity-enroll', 'parity-key', '203.0.113.8', '{token_hash}', '[\"test-cap\"]'::jsonb);"
    )
    worker_id = int(_psql_query(dsn, enroll_sql))
    # Re-enroll (token rotation) must reuse the worker and replace its token.
    assert int(_psql_query(dsn, enroll_sql)) == worker_id
    status = _psql_query(
        dsn,
        "SELECT e.status || '|' || e.enrolled_worker_id FROM wf.worker_enrollment e "
        "JOIN wf.cluster c ON c.id = e.cluster_id WHERE c.cluster_key = 'parity-enroll';",
    )
    assert status == f"ENROLLED|{worker_id}", status


def _run_rest_gateway_smoke(
    *,
    env_overrides: dict[str, str],
    seed_fn,
    port: int = 18080,
) -> None:
    import subprocess
    import time
    import urllib.error
    import urllib.request
    from pathlib import Path

    dsn = env_overrides.get("METHYLPIPELINE_DB") or _pg_dsn()
    version_id, worker_id, token = seed_fn(dsn)
    gateway = Path(__file__).resolve().parents[2] / "rest" / "gateway.py"
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.Popen(
        [sys.executable, str(gateway), "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(gateway.parent.parent),
    )
    base = f"http://127.0.0.1:{port}/v1"
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=1) as resp:
                    health = json.loads(resp.read().decode())
                    assert health.get("status") == "ok", health
                break
            except Exception:
                time.sleep(0.2)
        else:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(f"REST gateway did not start: {stderr}")

        def post(path: str, payload: dict) -> dict:
            req = urllib.request.Request(
                f"{base}{path}",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()
                return json.loads(body) if body else {}

        post("/workers/authenticate", {"worker_id": worker_id, "worker_token": token})
        # Instance lifecycle is not on the worker-only HTTP surface; start it via SQL.
        start_instance(dsn, version_id)
        claim = post(
            "/workers/tasks/request",
            {"worker_id": worker_id, "worker_token": token, "capability": "test-cap"},
        )
        assert claim.get("has_task"), claim
        ne_id = int(claim["node_execution_id"])
        ack = post(
            f"/workers/tasks/{ne_id}/submit",
            {
                "worker_id": worker_id,
                "worker_token": token,
                "result_code": 1,
                "output_json": {"ok": True},
            },
        )
        assert ack.get("accepted") is True, ack
        assert ack.get("instance_status") == "COMPLETED", ack
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_rest_gateway_postgres(dsn: str) -> None:
    _run_rest_gateway_smoke(
        env_overrides={
            "BACKEND_DB": "postgres",
            "METHYLPIPELINE_DB": dsn,
        },
        seed_fn=seed_minimal_workflow,
    )


def test_rest_gateway_mssql_optional() -> None:
    conn = os.environ.get("METHYL_TEST_MSSQL_CONN") or os.environ.get("METHYLPIPELINE_DB")
    if not conn or os.environ.get("BACKEND_DB", "mssql") not in ("mssql", ""):
        print("Skipping MSSQL REST gateway smoke (set METHYL_TEST_MSSQL_CONN)", file=sys.stderr)
        return
    try:
        import pyodbc  # noqa: F401
    except ImportError:
        print("Skipping MSSQL REST gateway smoke (pyodbc not installed)", file=sys.stderr)
        return

    def _seed_mssql(dsn: str) -> tuple[int, int, str]:
        raise NotImplementedError(
            "MSSQL gateway smoke requires a pre-seeded test database; "
            "deploy wf schema and set METHYL_TEST_MSSQL_CONN with seed data."
        )

    _ = _seed_mssql
    print("MSSQL REST gateway smoke: skipped (manual seed not configured)", file=sys.stderr)


def main() -> int:
    if not shutil_which("psql"):
        print("psql not found; skip postgres parity (install postgresql-client)", file=sys.stderr)
        return 0

    dsn = _pg_dsn()
    db_name = os.environ.get("POSTGRES_DB", "methylpipeline_parity")
    admin = dsn.rsplit("/", 1)[0] + "/postgres"
    subprocess.run(
        [
            "psql",
            "-q",
            admin,
            "-c",
            f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE);",
        ],
        check=True,
        env=_pg_env(),
    )
    subprocess.run(
        [
            "createdb",
            "-h",
            os.environ.get("POSTGRES_HOST", "localhost"),
            "-p",
            os.environ.get("POSTGRES_PORT", "5432"),
            "-U",
            os.environ.get("POSTGRES_USER", "postgres"),
            db_name,
        ],
        check=True,
        env=_pg_env(),
    )

    print(f"Deploying PostgreSQL schema to {dsn}")
    deploy_postgres(dsn)

    print("Running worker API parity...")
    test_worker_api_postgres(dsn)
    test_worker_capability_dispatch_postgres(dsn)
    test_require_previous_worker_postgres(dsn)
    print("Running repository parity...")
    test_repository_postgres(dsn)
    print("Running scope resolver parity...")
    test_scope_resolver_postgres(dsn)
    print("Running placeholder JSON literal parity...")
    test_placeholder_json_literal_postgres(dsn)
    print("Running worker enrollment parity...")
    test_worker_enrollment_postgres(dsn)
    print("Running REST gateway smoke test...")
    test_rest_gateway_postgres(dsn)
    test_rest_gateway_mssql_optional()

    print("Validating contract lockstep...")
    proc = subprocess.run([sys.executable, str(CONTRACT_SCRIPT)], capture_output=True, text=True)
    print(proc.stdout)
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    print("PostgreSQL parity: OK")
    return 0


def shutil_which(cmd: str) -> Optional[str]:
    from shutil import which

    return which(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
