"""Implementation of ``methyl-cfg verify-workflow``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.compiler import compile_domain_program_file
from domain.verify_workflow import (
    compare_compiled_to_db_nodes,
    verify_methylgrapher_bake,
    verify_program_file,
)


def run_verify_workflow(
    *,
    program: Path,
    site_path: Optional[Path] = None,
    procedure_path: Optional[Path] = None,
    check_db: bool = False,
    workflow_name: Optional[str] = None,
) -> Dict[str, Any]:
    report = verify_program_file(program)
    payload: Dict[str, Any] = report.to_dict()

    bake_findings: List[Dict[str, str]] = []
    if site_path and site_path.is_file():
        site = json.loads(site_path.read_text(encoding="utf-8"))
        profile_ac = None
        if procedure_path and procedure_path.is_file():
            proc = json.loads(procedure_path.read_text(encoding="utf-8"))
            profile_ac = proc.get("actionConfig")
        for f in verify_methylgrapher_bake(site, profile_ac):
            bake_findings.append(
                {"severity": f.severity, "code": f.code, "message": f.message}
            )
            report.findings.append(f)
    payload["methylgrapher_bake"] = bake_findings

    db_findings: List[Dict[str, str]] = []
    if check_db:
        compiled = compile_domain_program_file(program, enrich_context=False)
        name = workflow_name or compiled.workflow.name
        db_nodes = _fetch_db_action_nodes(name)
        for f in compare_compiled_to_db_nodes(compiled, db_nodes):
            db_findings.append(
                {"severity": f.severity, "code": f.code, "message": f.message}
            )
            report.findings.append(f)
    payload["db_compare"] = db_findings
    payload["ok"] = report.ok
    payload["findings"] = [
        {"severity": f.severity, "code": f.code, "message": f.message}
        for f in report.findings
    ]
    return payload


def _fetch_db_action_nodes(workflow_name: str) -> List[Dict[str, Any]]:
    """Load ACTION nodes for the active version of ``workflow_name`` from PostgreSQL."""
    from rest.connection import resolve_connection_config
    from rest.db.postgres import PostgresGatewayDb

    cfg = resolve_connection_config()
    db = PostgresGatewayDb(
        cfg.connection_string,
        schema_name=cfg.schema_name,
        use_managed_identity=cfg.use_managed_identity,
    )
    try:
        version_row = db._fetch_one(  # noqa: SLF001
            """
            SELECT wv.id
            FROM wf.workflow_version wv
            JOIN wf.workflow_def wd ON wd.id = wv.workflow_def_id
            WHERE wd.name = %s AND wv.is_active = TRUE
            ORDER BY wv.id DESC
            LIMIT 1
            """,
            (workflow_name,),
        )
        if not version_row or version_row.get("id") is None:
            return []
        version_id = int(version_row["id"])
        rows = db._fetch_all(  # noqa: SLF001
            """
            SELECT wn.node_key, wn.node_type, wa.action_name
            FROM wf.workflow_node wn
            LEFT JOIN wf.workflow_action wa ON wa.id = wn.workflow_action_id
            WHERE wn.workflow_version_id = %s
            """,
            (version_id,),
        )
    finally:
        db.close()
    return [
        {
            "node_key": row["node_key"],
            "node_type": row["node_type"],
            "action_name": row["action_name"],
        }
        for row in rows
    ]
