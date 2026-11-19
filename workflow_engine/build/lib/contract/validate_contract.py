#!/usr/bin/env python3
"""Validate DB object contract against sql_pg/ (PL/pgSQL)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_YAML = Path(__file__).resolve().parent / "db_objects.yaml"
SQL_DIR = ROOT / "sql_pg"

# Patterns to detect object definitions in deploy scripts
OBJECT_PATTERNS = [
    re.compile(
        r'CREATE\s+(?:OR\s+ALTER\s+)?(?:PROCEDURE|FUNCTION)\s+'
        r'(?:\["?([\w]+)"?\]|"?([\w]+)"?)'
        r'\.(?:\["?([\w]+)"?\]|"?([\w]+)"?)',
        re.I,
    ),
    re.compile(
        r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\s+'
        r'(?:\["?([\w]+)"?\]|"?([\w]+)"?)'
        r'\.(?:\["?([\w]+)"?\]|"?([\w]+)"?)',
        re.I,
    ),
]


def _normalize_match(m: re.Match[str]) -> str:
    groups = [g for g in m.groups() if g]
    if len(groups) >= 2:
        return f"{groups[0]}.{groups[1]}".lower()
    if groups:
        return groups[0].lower()
    return m.group(0).lower()


def load_required_objects() -> list[str]:
    if yaml is None:
        # Minimal fallback if PyYAML not installed
        text = CONTRACT_YAML.read_text(encoding="utf-8")
        names: list[str] = []
        for line in text.splitlines():
            if "name:" in line and any(
                s in line for s in ("wf.", "portal.", "dbo.", "cfg.", "rbac.")
            ):
                m = re.search(
                    r"name:\s*((?:wf|portal|dbo|cfg|rbac|RBAC)\.[\w.]+)", line
                )
                if m:
                    names.append(m.group(1).lower())
        return names

    data = yaml.safe_load(CONTRACT_YAML.read_text(encoding="utf-8"))
    names = []
    for section in data.get("objects", {}).values():
        for obj in section:
            if obj.get("required", True):
                names.append(str(obj["name"]).lower())
    return names


def scan_sql_dir(directory: Path) -> set[str]:
    found: set[str] = set()
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.sql")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pat in OBJECT_PATTERNS:
            for m in pat.finditer(text):
                found.add(_normalize_match(m))
    return found


# JSON payload columns must use jsonb, not text.
FORBIDDEN_JSON_COL = re.compile(
    r"^\s*(value_json|data_json|context_value_json|config_json|task_config_json)\s+"
    r"(?:text)\s",
    re.I | re.M,
)


def audit_json_column_types(directory: Path) -> int:
    """Fail if wf_* deploy scripts declare JSON payload columns as text."""
    exit_code = 0
    if not directory.is_dir():
        return exit_code
    for path in sorted(directory.glob("wf_*.sql")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in FORBIDDEN_JSON_COL.finditer(text):
            print(
                f"[postgres] forbidden JSON column type in {path.name}: "
                f"{match.group(0).strip()} (use jsonb)",
                file=sys.stderr,
            )
            exit_code = 1
    return exit_code


def main() -> int:
    required = load_required_objects()
    if not required:
        print("No required objects loaded from contract.", file=sys.stderr)
        return 1

    found = scan_sql_dir(SQL_DIR)
    exit_code = 0

    missing = [n for n in required if n not in found and not n.startswith("dbo.")]
    if missing:
        print(f"[postgres] missing {len(missing)} contract object(s):")
        for name in missing:
            print(f"  - {name}")
        exit_code = 1
    else:
        print(f"[postgres] all required contract objects present ({len(required)} checked)")

    exit_code |= audit_json_column_types(SQL_DIR)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
