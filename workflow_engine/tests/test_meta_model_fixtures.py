"""Cross-layer parity for Meta fixtures (§9): Pydantic + PostgreSQL sp_obj_insert."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

from goliath_app.meta.validation import validate_meta_document

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "meta_model" / "documents.json"
SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_meta_phase_d"))
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


@pytest.fixture(scope="module")
def fixture_cases() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]


def test_fixture_parity(pg_env: dict[str, str], fixture_cases: list[dict]) -> None:
    suffix = uuid.uuid4().hex[:8]
    cls = _psql(
        f"""INSERT INTO "Meta"."Classes" ("Name") VALUES ('FixtureCls_{suffix}') RETURNING "ID" """,
        pg_env,
    )
    type_id = _psql(
        f"""
        INSERT INTO wf.data_type (name, version, kind, schema_json)
        VALUES ('FixtureString_{suffix}', '1.0', 'string', '{{"type":"string"}}'::jsonb)
        RETURNING id
        """,
        pg_env,
    )
    for case in fixture_cases:
        doc = case["document"]
        props = {f["name"]: {"type": "string"} for f in case["fields"]}
        required = [f["name"] for f in case["fields"] if f["required"]]
        case_schema = {
            "type": "object",
            "properties": props,
            "required": required,
            "unevaluatedProperties": False,
        }

        for field in case["fields"]:
            _psql(
                f"""
                INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
                VALUES ({cls}, '{field["name"]}', {type_id}, {'true' if field["required"] else 'false'})
                ON CONFLICT ("ClassID", "Name") DO UPDATE SET "Required" = EXCLUDED."Required"
                """,
                pg_env,
            )

        if case["valid"]:
            validate_meta_document(case_schema, doc)
            obj_id = _psql(
                f"""SELECT "Meta".sp_obj_insert({cls}, '{json.dumps(doc)}'::jsonb)""",
                pg_env,
            )
            assert int(obj_id) > 0
        else:
            with pytest.raises(Exception):
                validate_meta_document(case_schema, doc)
            with pytest.raises(RuntimeError) as exc:
                _psql(
                    f"""SELECT "Meta".sp_obj_insert({cls}, '{json.dumps(doc)}'::jsonb)""",
                    pg_env,
                )
            if case.get("sql_error_substr"):
                assert case["sql_error_substr"] in str(exc.value)
