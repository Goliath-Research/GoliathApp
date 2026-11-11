"""GoliathApp must not reference child apps or standalone utilities (Phase D guard).

Scans repository sources for forbidden tokens (methyl, omics, crop, factory, realty,
groundstation, goliathalign, goliathextractor, and common Goliath* product spellings).
See ``docs/decoupling-plan.md`` for the phased removal plan.

Phase D10: no grandfather allowlist — any hit outside carved-out plan/test paths fails CI.
The SQL-specific extension-domain guard remains in ``test_goliathapp_sql_no_extension_domain.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_EXTENSIONS = frozenset(
    {
        ".py",
        ".sql",
        ".md",
        ".pas",
        ".dbd",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".dfm",
        ".dpr",
        ".dproj",
        ".design",
        ".dcomp",
    }
)

SKIP_DIR_NAMES = frozenset(
    {".git", "third_party", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
)

# Paths excluded from scanning (document the migration or implement the guard).
EXCLUDE_REL_PATHS = frozenset(
    {
        "docs/decoupling-plan.md",
        "workflow_engine/tests/test_goliathapp_no_child_app_tokens.py",
    }
)

# Child product packages and their deployment docs (intentional product names).
EXCLUDE_PATH_PREFIXES = (
    "products/",
    "docs/deploy/multi-product-platform-host.md",
)

# Case-insensitive child-app / utility tokens.
_COMPOUND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("methyl", re.compile(r"methyl", re.I)),
    ("omics", re.compile(r"omics", re.I)),
    ("goliathalign", re.compile(r"goliath\s*align|goliathalign", re.I)),
    ("goliathextractor", re.compile(r"goliath\s*extractor|goliathextractor", re.I)),
    (
        "groundstation",
        re.compile(r"ground\s*station|groundstation|goliathgroundstation", re.I),
    ),
    ("goliathcrop", re.compile(r"goliath\s*crop|goliathcrop", re.I)),
    ("goliathfactory", re.compile(r"goliath\s*factory|goliathfactory", re.I)),
    ("goliathrealty", re.compile(r"goliath\s*realty|goliathrealty", re.I)),
    ("goliathomics", re.compile(r"goliath\s*omics|goliathomics", re.I)),
)

_SHORT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("crop", re.compile(r"\bcrop\b", re.I)),
    ("factory", re.compile(r"\bfactory\b", re.I)),
    ("realty", re.compile(r"\brealty\b", re.I)),
)

# Python / Delphi / platform false positives for the word "factory".
_FACTORY_LINE_ALLOW = re.compile(
    r"default_factory|row_factory|dict_factory|TMVCServerFactory|"
    r"MVCFramework\.Server\.Factory|\.Server\.Factory|backend factory|"
    r"Rollouts\s*/\s*Factory",
    re.I,
)


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() not in SCAN_EXTENSIONS:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in EXCLUDE_REL_PATHS:
            continue
        if rel.startswith(EXCLUDE_PATH_PREFIXES):
            continue
        files.append(path)
    return files


def _line_has_forbidden_token(line: str) -> str | None:
    for name, pattern in _COMPOUND_PATTERNS:
        if pattern.search(line):
            return name
    for name, pattern in _SHORT_PATTERNS:
        if pattern.search(line):
            if name == "factory" and _FACTORY_LINE_ALLOW.search(line):
                continue
            return name
    return None


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    hits: list[tuple[int, str, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        token = _line_has_forbidden_token(line)
        if token:
            hits.append((lineno, token, line.strip()))
    return hits


def test_no_child_app_token_references() -> None:
    offenders: list[str] = []
    for path in _iter_scan_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        hits = _scan_file(path)
        if not hits:
            continue
        for lineno, token, snippet in hits[:5]:
            offenders.append(f"{rel}:{lineno} [{token}] {snippet[:120]}")
        if len(hits) > 5:
            offenders.append(f"{rel}: … +{len(hits) - 5} more lines")
    assert not offenders, (
        "Child-app or utility tokens in GoliathApp "
        "(see docs/decoupling-plan.md; only decoupling-plan.md is excluded):\n"
        + "\n".join(offenders)
    )
