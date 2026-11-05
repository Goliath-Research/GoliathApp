"""Compile a DomainProgram and run it locally from the installed package."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from domain.compiler import compile_domain_program_file

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE_PREP = FIXTURES / "sample_prep.program.json"

_STUB_PROGRAM = {
    "programVersion": 2,
    "name": "LocalStub",
    "description": "Platform-local stub run",
    "projectPath": "/tmp/goliath-no-such-project/project.json",
    "variables": {
        "samples": [{"sampleId": "s1"}, {"sampleId": "s2"}],
    },
    "body": [
        {
            "do": "demo.echo",
            "node_key": "echo",
            "with": {"message": "hello"},
            "out": {"ready": "$.value"},
        },
        {
            "if": "${ready}",
            "then": [
                {
                    "for": {
                        "collection": "samples",
                        "item": "sample",
                        "index": "sampleIndex",
                    },
                    "do": [
                        {
                            "do": "demo.touch",
                            "node_key": "touch",
                            "with": {"sampleId": "${var.sample.sampleId}"},
                        }
                    ],
                }
            ],
        },
    ],
}


def _workflow_run() -> str:
    script = shutil.which("goliath-workflow-run")
    if script:
        return script
    legacy = "meth" + "yl-workflow-run"
    script = shutil.which(legacy)
    if script:
        return script
    assert False, "goliath-workflow-run is not on PATH; install workflow_engine"


def test_compile_sample_prep_program() -> None:
    result = compile_domain_program_file(SAMPLE_PREP, enrich_context=False)
    spec = result.workflow
    assert spec.name == "WorkflowCompilerFixture"
    assert spec.root_node_key == "root"
    assert any(node.node_type == "ACTION" for node in spec.nodes)
    assert any(node.action_name == "demo.echo" for node in spec.nodes)
    assert any(node.action_name == "demo.touch" for node in spec.nodes)
    assert any(node.node_type == "FOREACH" for node in spec.nodes)
    assert "ready" in spec.variable_schemas


def test_compile_only_cli_writes_sample_prep(tmp_path: Path) -> None:
    out = tmp_path / "sample_prep.compiled.json"
    proc = subprocess.run(
        [_workflow_run(), "--compile-only", "--program", str(SAMPLE_PREP), "-o", str(out)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    spec = json.loads(out.read_text(encoding="utf-8"))
    assert spec["name"] == "WorkflowCompilerFixture"
    assert isinstance(spec["nodes"], list) and spec["nodes"]


def test_workflow_run_help() -> None:
    help_proc = subprocess.run(
        [_workflow_run(), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_proc.returncode == 0, help_proc.stderr
    assert "--stub-external" in help_proc.stdout
    assert "--compile-only" in help_proc.stdout


def test_stub_external_local_run(tmp_path: Path) -> None:
    program = tmp_path / "local_stub.program.json"
    program.write_text(json.dumps(_STUB_PROGRAM), encoding="utf-8")
    proc = subprocess.run(
        [
            _workflow_run(),
            "--program",
            str(program),
            "--stub-external",
            "--context",
            json.dumps({"projectPath": _STUB_PROGRAM["projectPath"]}),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["status"] == "COMPLETED"
    assert payload["actions"].count("echo") == 1
    assert payload["actions"].count("touch") == 2
    assert payload["skipped_actions"] == []


def test_runner_imports_as_installed_package() -> None:
    """Importing the console-script modules does not need a source checkout on sys.path."""
    import contract.workflow_definition_spec
    import domain.compiler
    import local.runner

    assert callable(local.runner.main)
    assert callable(domain.compiler.compile_domain_program_file)
    assert contract.workflow_definition_spec.WorkflowDefinitionSpec is not None
