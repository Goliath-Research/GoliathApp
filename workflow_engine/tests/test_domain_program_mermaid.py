"""Unit tests for the generic DomainProgram -> Mermaid renderer (domain.mermaid)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_ENGINE = REPO_ROOT / "workflow_engine"
if str(WORKFLOW_ENGINE) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_ENGINE))

from cfg.cli import main as cfg_cli_main  # noqa: E402
from domain.mermaid import (  # noqa: E402
    CategorySpec,
    build_catalog_docs,
    check_docs,
    load_categories_file,
    load_program_entry,
    render_program_mermaid,
    write_files,
)

FIXTURE_PATH = REPO_ROOT / "workflow_engine" / "tests" / "fixtures" / "sample_prep.program.json"
_SUBGRAPH_OPEN_RE = re.compile(r"^\s*subgraph\s+\S+\s+\[")
_SUBGRAPH_CLOSE_RE = re.compile(r"^\s*end\s*$")


def _assert_valid_mermaid_structure(diagram: str) -> None:
    lines = [line for line in diagram.splitlines() if line.strip()]
    assert lines[0] == "flowchart TD", f"unexpected header: {lines[0]!r}"
    depth = 0
    for line in lines[1:]:
        if _SUBGRAPH_OPEN_RE.match(line):
            depth += 1
        elif _SUBGRAPH_CLOSE_RE.match(line):
            depth -= 1
            assert depth >= 0, "unmatched Mermaid 'end' statement"
        # Semicolons inside labels break Mermaid 9 / mmdc parsing.
        if "classDef " not in line:
            assert ";" not in line, f"unexpected semicolon in Mermaid line: {line!r}"
    assert depth == 0, f"unclosed Mermaid subgraph(s): depth={depth}"


def test_render_neutral_platform_fixture() -> None:
    entry = load_program_entry(FIXTURE_PATH)
    assert entry.name == "WorkflowCompilerFixture"
    assert entry.actions == ("demo.echo", "demo.touch")
    assert entry.step_count == 2
    assert "ready" in entry.variables
    _assert_valid_mermaid_structure(entry.mermaid)
    assert 'n1(["Start"])' in entry.mermaid
    assert 'subgraph sg_1 ["FOREACH (parallel): sample in samples"]' in entry.mermaid
    assert "demo.echo<br/>out: ready" in entry.mermaid
    assert "demo.touch" in entry.mermaid
    assert "n1 --> n2" in entry.mermaid
    assert "n2 --> n3" in entry.mermaid
    assert "n3 --> n4" in entry.mermaid


def test_render_all_control_flow_constructs() -> None:
    program: dict[str, Any] = {
        "programVersion": 2,
        "name": "ControlFlowShowcase",
        "description": "Exercises triggers, wait, assign, if, switch, while, repeat, parallel, nested foreach.",
        "on": [{"event": "sensor.ready", "mode": "start_instance"}],
        "body": [
            {"wait": {"event": "operator.ack", "correlation": "${var.itemId}"}, "node_key": "wait_ack"},
            {"assign": "hasMore", "using": "workflow.const_bool", "node_key": "init_more"},
            {
                "while": "${hasMore}",
                "do": [
                    {"assign": "hasMore", "using": "workflow.json_path_bool", "node_key": "next_page"}
                ],
            },
            {
                "repeat": "${retry}",
                "do": [{"do": "demo.attempt", "node_key": "try_once"}],
            },
            {
                "if": "${gateOk}",
                "then": [
                    {
                        "for": {"in": {"ref": "groups"}, "as": "g", "parallel": True},
                        "do": [
                            {
                                "for": {"in": {"ref": "shards"}, "as": "s", "parallel": True},
                                "do": [
                                    {
                                        "parallel": [
                                            {"do": "demo.left", "node_key": "left_job"},
                                            {"do": "demo.right", "node_key": "right_job"},
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "else": [
                    {
                        "switch": "${mode}",
                        "cases": {
                            "fast": [{"do": "demo.fast"}],
                            "safe": [{"do": "demo.safe"}],
                        },
                        "default": [{"do": "demo.step_failed"}],
                    }
                ],
            },
        ],
    }
    diagram = render_program_mermaid(program)
    _assert_valid_mermaid_structure(diagram)
    assert "on: sensor.ready<br/>(start_instance)" in diagram
    assert "wait_ack<br/>WAIT: operator.ack<br/>corr: itemId" in diagram
    assert "while: hasMore?" in diagram
    assert "repeat: retry?" in diagram
    assert "FOREACH (parallel): g in groups x s in shards" in diagram
    assert 'subgraph sg_2 ["PARALLEL"]' in diagram
    assert "switch: mode" in diagram
    assert "classDef waitNode" in diagram
    assert "classDef failNode" in diagram
    assert "classDef decision" in diagram


def test_catalog_generation_check_and_cli(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    prog_a = {
        "programVersion": 2,
        "name": "AlphaFlow",
        "description": "First fixture",
        "phases": [
            {
                "name": "ingest",
                "foreach": {"collection": "items", "item": "item", "parallel": True},
                "steps": [{"action": "demo.run", "node_key": "run_item"}],
            }
        ],
    }
    prog_b = {
        "programVersion": 2,
        "name": "BetaFlow",
        "description": "Second fixture",
        "body": [{"do": "demo.finish", "node_key": "finish"}],
    }
    (fixtures_dir / "alpha.program.json").write_text(json.dumps(prog_a), encoding="utf-8")
    (fixtures_dir / "beta.program.json").write_text(json.dumps(prog_b), encoding="utf-8")

    cat_json = tmp_path / "categories.json"
    cat_json.write_text(
        json.dumps(
            [
                {
                    "slug": "core",
                    "title": "Core flows",
                    "intro": "Core demo workflows.",
                    "filenames": ["alpha.program.json"],
                }
            ]
        ),
        encoding="utf-8",
    )
    cats = load_categories_file(cat_json)
    assert cats == (
        CategorySpec(
            slug="core",
            title="Core flows",
            intro="Core demo workflows.",
            filenames=("alpha.program.json",),
        ),
    )

    md_files, mmd_files = build_catalog_docs(
        fixtures_dir,
        categories=cats,
        product_name="DemoApp",
    )
    assert set(md_files) == {"index.md", "core.md", "other-programs.md"}
    assert set(mmd_files) == {"alpha.mmd", "beta.mmd"}
    for mmd in mmd_files.values():
        _assert_valid_mermaid_structure(mmd)

    docs_dir = tmp_path / "docs_out"
    mmd_dir = tmp_path / "mmd_out"
    write_files(docs_dir, md_files, clean_ext=".md")
    assert check_docs(docs_dir, md_files) == []

    # Mutate one doc -> drift check fails
    (docs_dir / "core.md").write_text("# drifted\n", encoding="utf-8")
    assert check_docs(docs_dir, md_files)

    # CLI end-to-end via goliath-cfg render-mermaid
    rc = cfg_cli_main(
        [
            "render-mermaid",
            "--fixtures-dir",
            str(fixtures_dir),
            "--docs-dir",
            str(docs_dir),
            "--emit-mmd-dir",
            str(mmd_dir),
            "--categories-json",
            str(cat_json),
            "--product-name",
            "DemoApp",
        ]
    )
    assert rc == 0
    assert (mmd_dir / "alpha.mmd").is_file()
    assert (mmd_dir / "beta.mmd").is_file()

    rc_check = cfg_cli_main(
        [
            "render-mermaid",
            "--fixtures-dir",
            str(fixtures_dir),
            "--docs-dir",
            str(docs_dir),
            "--categories-json",
            str(cat_json),
            "--product-name",
            "DemoApp",
            "--check",
        ]
    )
    assert rc_check == 0
