"""Meta model Phase A: class hierarchy, ObjValues, instance link triggers (docs/meta-model.md §9 subset)."""

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
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_meta_phase_a"))
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


def _which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


@pytest.fixture(scope="module")
def pg_env() -> dict[str, str]:
    if not _which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(SQL_PG / "apply_schema.sh")], env=env, check=True)
    return env


def test_class_hierarchy_fk_and_closure(pg_env: dict[str, str]) -> None:
    root = _psql(
        """
        INSERT INTO "Meta"."Classes" ("Name") VALUES ('MetaTestRoot')
        RETURNING "ID"
        """,
        pg_env,
    )
    child = _psql(
        f"""
        INSERT INTO "Meta"."Classes" ("Name", "ParentID")
        VALUES ('MetaTestChild', {root})
        RETURNING "ID"
        """,
        pg_env,
    )
    depth = _psql(
        f'SELECT "Depth" FROM "Meta"."Classes" WHERE "ID" = {child}',
        pg_env,
    )
    assert int(depth) == 1
    closure = _psql(
        f"""
        SELECT count(*) FROM "Meta"."ClassClosure"
        WHERE "AncestorID" = {root} AND "DescendantID" = {child} AND "Depth" = 1
        """,
        pg_env,
    )
    assert int(closure) == 1


def test_class_hierarchy_rejects_cycle(pg_env: dict[str, str]) -> None:
    a = _psql(
        """INSERT INTO "Meta"."Classes" ("Name") VALUES ('CycleA') RETURNING "ID" """,
        pg_env,
    )
    b = _psql(
        f"""INSERT INTO "Meta"."Classes" ("Name", "ParentID") VALUES ('CycleB', {a}) RETURNING "ID" """,
        pg_env,
    )
    with pytest.raises(RuntimeError, match="cycle"):
        _psql(f'UPDATE "Meta"."Classes" SET "ParentID" = {b} WHERE "ID" = {a}', pg_env)


def test_objvalues_table_and_indexes(pg_env: dict[str, str]) -> None:
    cls = _psql(
        """INSERT INTO "Meta"."Classes" ("Name") VALUES ('ObjValCls') RETURNING "ID" """,
        pg_env,
    )
    obj = _psql(
        f'INSERT INTO "Meta"."Objs" ("ClassID") VALUES ({cls}) RETURNING "ID"',
        pg_env,
    )
    _psql(
        f"""
        INSERT INTO "Meta"."ObjValues" ("ObjID", "ClassID", "Data")
        VALUES ({obj}, {cls}, '{{"k": "v"}}'::jsonb)
        """,
        pg_env,
    )
    hit = _psql(
        f"""
        SELECT "Data"->>'k' FROM "Meta"."ObjValues"
        WHERE "ObjID" = {obj} AND "ClassID" = {cls}
        """,
        pg_env,
    )
    assert hit == "v"


def test_instance_link_permitted_and_max_card(pg_env: dict[str, str]) -> None:
    link_type = _psql(
        """
        INSERT INTO "Meta"."LinkTypes" ("Name")
        VALUES ('TestLinkType')
        RETURNING "ID"
        """,
        pg_env,
    )
    src_cls = _psql(
        """INSERT INTO "Meta"."Classes" ("Name") VALUES ('LinkSrc') RETURNING "ID" """,
        pg_env,
    )
    tgt_cls = _psql(
        """INSERT INTO "Meta"."Classes" ("Name") VALUES ('LinkTgt') RETURNING "ID" """,
        pg_env,
    )
    meta_link = _psql(
        f"""
        INSERT INTO "Meta"."MetaLinks" ("ClassID", "Name", "TargetClassID", "MaxCard")
        VALUES ({src_cls}, 'rel', {tgt_cls}, 1)
        RETURNING "ID"
        """,
        pg_env,
    )
    o1 = _psql(
        f'INSERT INTO "Meta"."Objs" ("ClassID") VALUES ({src_cls}) RETURNING "ID"',
        pg_env,
    )
    o2 = _psql(
        f'INSERT INTO "Meta"."Objs" ("ClassID") VALUES ({tgt_cls}) RETURNING "ID"',
        pg_env,
    )
    o3 = _psql(
        f'INSERT INTO "Meta"."Objs" ("ClassID") VALUES ({tgt_cls}) RETURNING "ID"',
        pg_env,
    )
    name = f"inst-{uuid.uuid4().hex[:8]}"
    _psql(
        f"""
        INSERT INTO "Meta"."Links"
          ("Name", "ClassID1", "ClassID2", "LinkTypeID", "MetaLinkID", "ObjID1", "ObjID2")
        VALUES ('{name}', {src_cls}, {tgt_cls}, {link_type}, {meta_link}, {o1}, {o2})
        """,
        pg_env,
    )
    with pytest.raises(RuntimeError, match="MaxCard"):
        _psql(
            f"""
            INSERT INTO "Meta"."Links"
              ("Name", "ClassID1", "ClassID2", "LinkTypeID", "MetaLinkID", "ObjID1", "ObjID2")
            VALUES ('{name}-2', {src_cls}, {tgt_cls}, {link_type}, {meta_link}, {o1}, {o3})
            """,
            pg_env,
        )
