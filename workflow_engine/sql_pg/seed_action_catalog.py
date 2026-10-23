#!/usr/bin/env python3
"""Seed wf.workflow_action + wf.workflow_action_schema from goliath_app catalogs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goliath_app.actions.registry import load_action_catalog
from goliath_app.actions.schema_export import export_action_schemas


def _connect():
    import psycopg

    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ.get("PGPASSWORD"),
    )


def seed(conn) -> int:
    count = 0
    with conn.cursor() as cur:
        for spec in load_action_catalog():
            cur.execute(
                """
                CALL wf.wf_repo_upsert_semantic_action(
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    spec.action_name,
                    spec.resolved_capability,
                    spec.namespace,
                    spec.level.value,
                    spec.resolved_exposure.value,
                    spec.display_name,
                    spec.schema_version,
                    spec.overrides,
                    None,
                    "in_process",
                    spec.in_process_handler,
                ),
            )
            for row in export_action_schemas(spec):
                cur.execute(
                    """
                    CALL wf.wf_repo_upsert_action_schema(
                      %s, %s, %s::jsonb, %s, %s, %s
                    )
                    """,
                    (
                        row.action_name,
                        row.direction,
                        json.dumps(row.schema_json),
                        row.schema_id,
                        row.schema_version,
                        row.content_hash,
                    ),
                )
            count += 1
    conn.commit()
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-db", action="store_true", help="Apply rows via libpq")
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    args = parser.parse_args()

    catalog = load_action_catalog()
    if args.dry_run or not args.use_db:
        for spec in catalog:
            print(spec.action_name, spec.namespace, spec.level.value)
        return 0

    for key in ("PGHOST", "PGDATABASE", "PGUSER"):
        if not os.environ.get(key):
            print(f"missing required env {key}", file=sys.stderr)
            return 2

    with _connect() as conn:
        seeded = seed(conn)
    print(f"seeded {seeded} actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
