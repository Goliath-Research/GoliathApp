"""Generic redaction and root scope defaults (no application key names in the platform)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_engine.tests.test_portal_record_editors import (  # noqa: F401  (pytest fixtures)
    _lit,
    _psql,
    editor_env,
)

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"


def test_redaction_removes_credential_keys_at_any_depth(editor_env: dict[str, str]) -> None:  # noqa: F811
    payload = {
        "a": 1,
        "credentials": {"k": "v"},
        "anySource": {"uri": "s3://x", "credentials": {"k": "v"}, "accessKey": "z"},
        "samples": [{"id": 1, "nested": {"password": "p", "keep": True}}],
        "list": [1, "two"],
    }
    out = json.loads(_psql(f"SELECT portal.fn_redact_json_credentials({_lit(payload)}::jsonb)", editor_env))
    assert out == {
        "a": 1,
        "anySource": {"uri": "s3://x"},
        "samples": [{"id": 1, "nested": {"keep": True}}],
        "list": [1, "two"],
    }


def test_redaction_sql_names_no_application_keys() -> None:
    text = (SQL_PG / "portal_study_ops_api.sql").read_text(encoding="utf-8")
    body = text[text.index("FUNCTION portal.fn_redact_json_credentials") :]
    body = body[: body.index("$$;")]
    for key in ("fastq", "h5", "sampleDestination", "sampleStorage"):
        assert key not in body


def test_compiler_root_scope_defaults_are_declared_by_the_program() -> None:
    from domain.compiler import compile_domain_program
    from domain.program import DomainProgram

    base = {"name": "p", "projectPath": "/p", "body": []}
    names = [d.var_name for d in compile_domain_program(DomainProgram.model_validate(base)).workflow.scope_defaults]
    assert names == ["projectPath"]
    declared = DomainProgram.model_validate({**base, "scopeDefaults": ["runDir", "projectPath"]})
    names = [d.var_name for d in compile_domain_program(declared).workflow.scope_defaults]
    assert names == ["projectPath", "runDir"]
    with pytest.raises(ValueError, match="invalid scopeDefaults"):
        compile_domain_program(DomainProgram.model_validate({**base, "scopeDefaults": ["bad name"]}))


def test_compiler_names_no_application_scope_vars() -> None:
    text = (Path(__file__).resolve().parents[1] / "domain" / "compiler.py").read_text(encoding="utf-8")
    assert "centroid" not in text
