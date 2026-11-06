#!/usr/bin/env python3
"""Validate every ```mermaid block in docs (and worker protocol) with mmdc.

CI regression: catches parse errors (for example stray semicolons in sequenceDiagram
arrow text) before publishing. Uses the same Mermaid major version as MkDocs
(see mkdocs.yml plugins.mermaid2.version).

Usage (from repo root):

    python3 scripts/validate_mermaid_docs.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Keep in sync with mkdocs.yml -> plugins -> mermaid2 -> version (major).
MERMAID_CLI_VERSION = "10.9.1"

_PUPPETEER_CONFIG = REPO_ROOT / "scripts" / "puppeteer-mermaid-ci.json"

MERMAID_FENCE = re.compile(r"^```mermaid\s*\n(?P<body>.*?)^```\s*$", re.MULTILINE | re.DOTALL)

PATHS = (
    REPO_ROOT / "docs",
    REPO_ROOT / "workers" / "WORKER_PROTOCOL.md",
)


def _iter_markdown_files() -> list[Path]:
    out: list[Path] = []
    for entry in PATHS:
        if entry.is_file():
            out.append(entry)
        elif entry.is_dir():
            out.extend(sorted(entry.glob("**/*.md")))
    return out


def main() -> int:
    errors: list[str] = []
    total = 0
    for md_path in _iter_markdown_files():
        text = md_path.read_text(encoding="utf-8")
        for idx, m in enumerate(MERMAID_FENCE.finditer(text), start=1):
            total += 1
            body = m.group("body").strip()
            if not body.endswith("\n"):
                body += "\n"
            with tempfile.TemporaryDirectory() as td:
                tdir = Path(td)
                src = tdir / "diagram.mmd"
                svg = tdir / "diagram.svg"
                src.write_text(body, encoding="utf-8")
                proc = subprocess.run(
                    [
                        "npx",
                        "--yes",
                        f"@mermaid-js/mermaid-cli@{MERMAID_CLI_VERSION}",
                        "mmdc",
                        "-p",
                        str(_PUPPETEER_CONFIG),
                        "-i",
                        str(src),
                        "-o",
                        str(svg),
                        "-q",
                    ],
                    cwd=td,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    rel = md_path.relative_to(REPO_ROOT)
                    msg = proc.stderr.strip() or proc.stdout.strip() or "(no stderr)"
                    errors.append(f"{rel} diagram #{idx}:\n{msg}")

    if errors:
        print("Mermaid validation failed:", file=sys.stderr)
        for block in errors:
            print(block, file=sys.stderr)
            print("---", file=sys.stderr)
        return 1

    print(f"OK: {total} Mermaid diagram(s) validated (mermaid-cli {MERMAID_CLI_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
