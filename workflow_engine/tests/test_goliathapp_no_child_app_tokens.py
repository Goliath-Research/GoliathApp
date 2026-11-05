"""GoliathApp must not reference child apps or standalone utilities (Phase D guard).

Scans repository sources for forbidden tokens (methyl, omics, crop, factory, realty,
groundstation, goliathalign, goliathextractor, and common Goliath* product spellings).
See ``docs/decoupling-plan.md`` for the phased removal plan.
Known legacy references are listed in ``child_app_token_allowlist.txt``; shrink that
list each decoupling phase. New files and new references outside the allowlist fail CI.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).resolve().parent / "child_app_token_allowlist.txt"

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
        "workflow_engine/tests/child_app_token_allowlist.txt",
        "workflow_engine/tests/test_goliathapp_no_child_app_tokens.py",
    }
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

# ``workflow_engine/pyproject.toml`` keeps ``methyl-*`` console scripts one release (D8→D10).
_PYPROJECT_REL = "workflow_engine/pyproject.toml"
_ONE_RELEASE_CONSOLE_ALIAS = re.compile(r"^\s*methyl-[a-z0-9-]+\s*=", re.I)
_ONE_RELEASE_ALIAS_BLOCK_START = re.compile(
    r"one-release console-script aliases", re.I
)
_ONE_RELEASE_ALIAS_BLOCK_END = re.compile(r"end one-release console-script aliases", re.I)


def _line_allowed_one_release_packaging(rel: str, line: str, *, in_alias_block: bool) -> bool:
    if rel != _PYPROJECT_REL:
        return False
    if in_alias_block:
        return True
    if _ONE_RELEASE_CONSOLE_ALIAS.match(line):
        return True
    if _ONE_RELEASE_ALIAS_BLOCK_START.search(line) or _ONE_RELEASE_ALIAS_BLOCK_END.search(
        line
    ):
        return True
    return False


def _load_allowlist() -> frozenset[str]:
    paths: set[str] = set()
    for raw in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            paths.add(line.replace("\\", "/"))
    return frozenset(paths)


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
    rel = path.relative_to(REPO_ROOT).as_posix()
    hits: list[tuple[int, str, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    in_alias_block = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if rel == _PYPROJECT_REL:
            if _ONE_RELEASE_ALIAS_BLOCK_END.search(line):
                in_alias_block = False
                continue
            if _ONE_RELEASE_ALIAS_BLOCK_START.search(line):
                in_alias_block = True
        if _line_allowed_one_release_packaging(rel, line, in_alias_block=in_alias_block):
            continue
        token = _line_has_forbidden_token(line)
        if token:
            hits.append((lineno, token, line.strip()))
    return hits


def test_child_app_token_allowlist_paths_exist_and_offend() -> None:
    """Every allowlisted path must still exist and still contain forbidden tokens."""
    allowlisted = _load_allowlist()
    missing: list[str] = []
    stale: list[str] = []
    for rel in sorted(allowlisted):
        path = REPO_ROOT / rel
        if not path.is_file():
            missing.append(rel)
            continue
        if not _scan_file(path):
            stale.append(rel)
    problems: list[str] = []
    if missing:
        problems.append("Allowlist paths missing on disk:\n" + "\n".join(missing))
    if stale:
        problems.append(
            "Allowlist paths no longer contain forbidden tokens (remove from allowlist):\n"
            + "\n".join(stale)
        )
    assert not problems, "\n\n".join(problems)


def test_no_new_child_app_token_references() -> None:
    allowlisted = _load_allowlist()
    offenders: list[str] = []
    for path in _iter_scan_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        hits = _scan_file(path)
        if not hits:
            continue
        if rel in allowlisted:
            continue
        for lineno, token, snippet in hits[:5]:
            offenders.append(f"{rel}:{lineno} [{token}] {snippet[:120]}")
        if len(hits) > 5:
            offenders.append(f"{rel}: … +{len(hits) - 5} more lines")
    assert not offenders, (
        "Child-app or utility tokens outside the allowlist "
        f"(update {ALLOWLIST.name} only when cleaning a file in a D phase):\n"
        + "\n".join(offenders)
    )
