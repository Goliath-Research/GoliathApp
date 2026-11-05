"""Meta model Phase C: sp_obj_* and ObjValues key validation (docs/meta-model.md §4.4)."""

from __future__ import annotations

import os
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
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_meta_phase_c"))
    if env.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    elif env.get("PGHOST", "localhost") in ("localhost", "127.0.0.1"):
        env.setdefault("PGPASSWORD", "methyl")
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


def test_sp_obj_insert_and_unknown_key_rejected(pg_env: dict[str, str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    cls = _psql(
        f"""INSERT INTO "Meta"."Classes" ("Name") VALUES ('ObjCls_{suffix}') RETURNING "ID" """,
        pg_env,
    )
    type_id = _psql(
        f"""
        INSERT INTO wf.data_type (name, version, kind, schema_json)
        VALUES ('Field_{suffix}', '1.0', 'string', '{{"type":"string"}}'::jsonb)
        RETURNING id
        """,
        pg_env,
    )
    _psql(
        f"""
        INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
        VALUES ({cls}, 'Code', {type_id}, true)
        """,
        pg_env,
    )
    obj_id = _psql(
        f"""SELECT "Meta".sp_obj_insert({cls}, '{{"Code": "abc"}}'::jsonb)""",
        pg_env,
    )
    assert int(obj_id) > 0
    with pytest.raises(RuntimeError, match="unknown field"):
        _psql(
            f"""
            UPDATE "Meta"."ObjValues"
            SET "Data" = '{{"Code": "x", "Extra": 1}}'::jsonb
            WHERE "ObjID" = {obj_id} AND "ClassID" = {cls}
            """,
            pg_env,
        )
