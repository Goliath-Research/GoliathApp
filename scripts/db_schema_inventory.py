#!/usr/bin/env python3
"""
Live object inventory for controlled PostgreSQL schemas.

Captures tables, views, routines, and cross-schema FKs for:
  wf, cfg, portal, RBAC, Meta, Contract, Onboarding

Usage:
  source .venv/bin/activate

  export PGHOST=localhost PGDATABASE=goliath PGUSER=postgres PGPASSWORD='...' PGSSLMODE=prefer
  python scripts/db_schema_inventory.py

Writes JSON + markdown under workflow_engine/contract/.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "workflow_engine" / "contract"
CONTROLLED_SCHEMAS = (
    "wf",
    "cfg",
    "portal",
    "RBAC",
    "Meta",
    "Contract",
    "Onboarding",
)


@dataclass
class Inventory:
    backend: str
    database: str
    captured_at_utc: str
    tables: Dict[str, List[str]] = field(default_factory=dict)
    views: Dict[str, List[str]] = field(default_factory=dict)
    routines: Dict[str, List[str]] = field(default_factory=dict)
    cross_schema_fks: List[Dict[str, str]] = field(default_factory=list)

    def normalized_tables(self) -> Set[str]:
        out: Set[str] = set()
        for schema, names in self.tables.items():
            for name in names:
                out.add(f"{schema}.{name}".lower())
        return out

    def normalized_routines(self) -> Set[str]:
        out: Set[str] = set()
        for schema, names in self.routines.items():
            for name in names:
                out.add(f"{schema}.{name}".lower())
        return out


def _pg_connect():
    import psycopg  # type: ignore

    host = os.environ.get("PGHOST") or os.environ.get("POSTGRES_HOST", "")
    port = os.environ.get("PGPORT") or os.environ.get("POSTGRES_PORT", "5432")
    database = (
        os.environ.get("PGDATABASE")
        or os.environ.get("POSTGRES_DB")
        or "goliath"
    )
    user = os.environ.get("PGUSER") or os.environ.get("POSTGRES_USER", "")
    password = os.environ.get("PGPASSWORD") or os.environ.get("POSTGRES_PASSWORD", "")
    sslmode = os.environ.get("PGSSLMODE", "prefer")
    if not host or not user:
        raise SystemExit(
            "Set PGHOST/POSTGRES_HOST and PGUSER/POSTGRES_USER "
            "(and PGPASSWORD/POSTGRES_PASSWORD or PGPASSFILE)."
        )
    conn = psycopg.connect(
        host=host,
        port=int(port),
        dbname=database,
        user=user,
        password=password or None,
        sslmode=sslmode,
        connect_timeout=30,
    )
    return conn, database


def inventory_postgres() -> Inventory:
    conn, database = _pg_connect()
    inv = Inventory(
        backend="postgres",
        database=database,
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    schema_filter = ", ".join(
        f"'{s}'" for s in CONTROLLED_SCHEMAS
    ) + ", " + ", ".join(f"'{s.lower()}'" for s in CONTROLLED_SCHEMAS)
    try:
        with conn.cursor() as cur:
            cur.execute(  # pyrefly: ignore[no-matching-overload]
                f"""
                SELECT n.nspname, c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r'
                  AND n.nspname IN ({schema_filter})
                ORDER BY n.nspname, c.relname
                """
            )
            for schema, name in cur.fetchall():
                inv.tables.setdefault(schema, []).append(name)

            cur.execute(  # pyrefly: ignore[no-matching-overload]
                f"""
                SELECT n.nspname, c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'v'
                  AND n.nspname IN ({schema_filter})
                ORDER BY n.nspname, c.relname
                """
            )
            for schema, name in cur.fetchall():
                inv.views.setdefault(schema, []).append(name)

            cur.execute(  # pyrefly: ignore[no-matching-overload]
                f"""
                SELECT n.nspname, p.proname
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname IN ({schema_filter})
                  AND p.prokind IN ('f', 'p')
                ORDER BY n.nspname, p.proname
                """
            )
            for schema, name in cur.fetchall():
                inv.routines.setdefault(schema, []).append(name)

            cur.execute(  # pyrefly: ignore[no-matching-overload]
                f"""
                SELECT tc.constraint_name,
                       tc.table_schema, tc.table_name,
                       ccu.table_schema, ccu.table_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.constraint_schema = tc.constraint_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema IN ({schema_filter})
                  AND ccu.table_schema IN ({schema_filter})
                  AND tc.table_schema <> ccu.table_schema
                ORDER BY tc.constraint_name
                """
            )
            for fk_name, p_schema, p_table, r_schema, r_table in cur.fetchall():
                inv.cross_schema_fks.append(
                    {
                        "fk_name": fk_name,
                        "parent": f"{p_schema}.{p_table}",
                        "referenced": f"{r_schema}.{r_table}",
                    }
                )
    finally:
        conn.close()
    return inv


def _merge_case_variants(bucket: Dict[str, List[str]], schema: str) -> List[str]:
    primary = list(bucket.get(schema, []))
    lower = schema.lower()
    if lower == schema:
        return primary
    seen = set(primary)
    for name in bucket.get(lower, []):
        if name not in seen:
            primary.append(name)
            seen.add(name)
    return primary


def write_outputs(inv: Inventory) -> Tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "schema_inventory_live.json"
    md_path = OUT_DIR / "schema_inventory_live.md"
    payload: Dict[str, Any] = {"postgres": asdict(inv)}
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Live schema inventory (PostgreSQL)",
        "",
        f"Captured: `{inv.captured_at_utc}`",
        "",
        "Controlled schemas: "
        + ", ".join(f"`{s}`" for s in CONTROLLED_SCHEMAS)
        + ".",
        "",
        f"## PostgreSQL (`{inv.database}`)",
        "",
    ]
    for schema in CONTROLLED_SCHEMAS:
        tables = _merge_case_variants(inv.tables, schema)
        routines = _merge_case_variants(inv.routines, schema)
        lines.append(f"- `{schema}`: {len(tables)} tables, {len(routines)} routines")
    lines.append("")
    lines.append(f"Cross-schema FKs: {len(inv.cross_schema_fks)}")
    lines.append("")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    print("Inventorying PostgreSQL …", flush=True)
    inv = inventory_postgres()
    json_path, md_path = write_outputs(inv)
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
