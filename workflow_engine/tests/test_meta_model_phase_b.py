"""Meta model Phase B: JSON Schema generation and class views (docs/meta-model.md §4.2, §5)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_meta_phase_b"))
    if env.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    elif env.get("PGHOST", "localhost") in ("localhost", "127.0.0.1"):
        env.setdefault("PGPASSWORD", "goliath")
    return env


def _psql(sql: str, env: dict[str, str]) -> str:
    proc = subprocess.run(
        ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-c", sql],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


@pytest.fixture(scope="module")
def pg_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(SQL_PG / "apply_schema.sh")], env=env, check=True)
    return env


def test_fn_class_json_schema_allof_and_publish(pg_env: dict[str, str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    parent = _psql(
        f"""INSERT INTO "Meta"."Classes" ("Name") VALUES ('SchemaParent_{suffix}') RETURNING "ID" """,
        pg_env,
    )
    child = _psql(
        f"""
        INSERT INTO "Meta"."Classes" ("Name", "ParentID")
        VALUES ('SchemaChild_{suffix}', {parent})
        RETURNING "ID"
        """,
        pg_env,
    )
    type_id = _psql(
        f"""
        INSERT INTO wf.data_type (name, version, kind, schema_json)
        VALUES ('Barcode_{suffix}', '1.0', 'string', '{{"type":"string"}}'::jsonb)
        RETURNING id
        """,
        pg_env,
    )
    _psql(
        f"""
        INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
        VALUES ({child}, 'Barcode', {type_id}, true)
        """,
        pg_env,
    )
    schema_raw = _psql(
        f"SELECT \"Meta\".fn_class_json_schema({child})::text",
        pg_env,
    )
    schema = json.loads(schema_raw)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["unevaluatedProperties"] is False
    assert any(
        "allOf" in ref or "$ref" in ref
        for ref in schema.get("allOf", [])
    ) or schema.get("allOf")
    assert "Barcode" in schema.get("properties", {})

    type_row = _psql(
        f"""
        SELECT t.version, t.content_hash IS NOT NULL
        FROM "Meta"."Classes" c
        JOIN wf.data_type t ON t.id = c."TypeID"
        WHERE c."ID" = {child}
        """,
        pg_env,
    )
    version, has_hash = type_row.split("|")
    assert re.match(r"^\d+\.\d+$", version)
    assert has_hash == "t"


def test_class_view_regenerated(pg_env: dict[str, str]) -> None:
    cls = _psql(
        """INSERT INTO "Meta"."Classes" ("Name", "TableName") VALUES ('ViewLeaf', 'ViewLeaf') RETURNING "ID" """,
        pg_env,
    )
    _psql(f'SELECT "Meta".sp_class_regenerate_views({cls})', pg_env)
    exists = _psql(
        """
        SELECT count(*) FROM information_schema.views
        WHERE table_schema = 'Meta' AND table_name = 'VViewLeaf'
        """,
        pg_env,
    )
    assert int(exists) == 1
