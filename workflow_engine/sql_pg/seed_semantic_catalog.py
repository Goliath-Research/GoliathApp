#!/usr/bin/env python3
"""Seed portal semantic registry from goliath_app.semantic catalog."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goliath_app.semantic.catalog import SEMANTIC_CATALOG, SEMANTIC_REQUESTS
from goliath_app.semantic.export import _entity_by_code, _schema_id, content_hash_for


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
    entity_ids: dict[str, int] = {}
    with conn.cursor() as cur:
        for entity in SEMANTIC_CATALOG:
            row_schema = entity.row_model.model_json_schema(mode="serialization")
            entity_hash = content_hash_for(
                {
                    "namespace": entity.namespace,
                    "code": entity.code,
                    "schema_version": entity.schema_version,
                    "row_schema": row_schema,
                    "attributes": [a.__dict__ for a in entity.attributes],
                }
            )
            cur.execute(
                """
                CALL portal.sp_semantic_register_entity(
                  %s, %s, %s, %s, %s, %s, %s, %s, NULL
                )
                """,
                (
                    entity.namespace,
                    entity.code,
                    entity.display_name,
                    entity.description,
                    _schema_id(entity),
                    entity.schema_version,
                    entity_hash,
                    entity.storage_relation,
                ),
            )
            cur.execute(
                """
                SELECT id FROM portal.semantic_entity
                WHERE namespace = %s AND code = %s
                """,
                (entity.namespace, entity.code),
            )
            row = cur.fetchone()
            assert row is not None
            entity_ids[entity.code] = int(row[0])
            for attr in entity.attributes:
                cur.execute(
                    """
                    CALL portal.sp_semantic_register_attribute(
                      %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        entity_ids[entity.code],
                        attr.code,
                        attr.column_name,
                        attr.json_type,
                        attr.role,
                        list(attr.filterable_ops),
                    ),
                )
            count += 1

        for req in SEMANTIC_REQUESTS:
            entity = _entity_by_code(req.entity_code)
            params_schema = req.params_model.model_json_schema(mode="serialization")
            result_schema = req.result_row_model.model_json_schema(mode="serialization")
            filter_payload = (
                req.filter_template.model_dump(mode="json") if req.filter_template else None
            )
            req_hash = content_hash_for(
                {
                    "request_code": req.request_code,
                    "version": req.version,
                    "params_schema": params_schema,
                    "result_schema": result_schema,
                    "filter_template": filter_payload,
                }
            )
            row_type = f"{entity.namespace}_{entity.code}_row".replace(".", "_")
            cur.execute(
                """
                CALL portal.sp_semantic_register_request(
                  %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s, %s, %s
                )
                """,
                (
                    req.request_code,
                    req.version,
                    req.namespace,
                    entity_ids[req.entity_code],
                    req.target_kind,
                    req.target_name,
                    row_type,
                    json.dumps(params_schema),
                    json.dumps(result_schema),
                    req_hash,
                    json.dumps(filter_payload) if filter_payload is not None else None,
                    req.required_permission,
                    req.max_rows,
                    req.base_namespace,
                ),
            )
            count += 1
    conn.commit()
    return count


def main() -> int:
    if not os.environ.get("PGHOST"):
        print("Set PGHOST/PGDATABASE/PGUSER for seed_semantic_catalog", file=sys.stderr)
        return 2
    with _connect() as conn:
        n = seed(conn)
    print(f"Seeded {n} semantic registry objects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
