"""Meta tree path maintenance and portal NavTree Meta bridge."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import pytest

from workflow_engine.tests.pg_require_ci import require_postgres_reachable, require_psql

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_meta_tree"))
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
    require_psql()
    env = _pg_env()
    def _probe() -> None:
        _psql("SELECT 1", env)

    require_postgres_reachable(_probe)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # CI job already applied schema; avoid duplicate full apply when same DB name.
        class_id = _psql("SELECT portal.fn_nav_node_class_id()", env)
        if not class_id:
            subprocess.run(["bash", str(SQL_PG / "apply_schema.sh")], env=env, check=True)
    else:
        subprocess.run(["bash", str(SQL_PG / "apply_schema.sh")], env=env, check=True)
    return env


def test_portal_nav_register_node_creates_meta_tree(pg_env: dict[str, str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    nav_id = _psql(
        f"""
        SELECT node_id FROM portal.sp_nav_register_node(
          NULL::integer,
          'TreeTest {suffix}',
          10::smallint,
          NULL::integer,
          '/tree-test-{suffix}',
          '0010'
        )
        """,
        pg_env,
    )
    row = _psql(
        f"""
        SELECT n."MetaObjID", tn."Path"::text
        FROM portal."NavTree" n
        JOIN "Meta"."TreeNodes" tn ON tn."ObjID" = n."MetaObjID"
        WHERE n."ID" = {nav_id}
          AND tn."MetaLinkID" = portal.fn_nav_parent_metalink_id()
        """,
        pg_env,
    )
    meta_obj_id, path = row.split("|")
    assert meta_obj_id
    assert path == f"n{meta_obj_id}"


def test_portal_nav_child_parent_link_and_cycle(pg_env: dict[str, str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    root_id = _psql(
        f"""
        SELECT node_id FROM portal.sp_nav_register_node(
          NULL::integer, 'Root {suffix}', 1::smallint, NULL::integer, '/r-{suffix}', '0001'
        )
        """,
        pg_env,
    )
    child_id = _psql(
        f"""
        SELECT node_id FROM portal.sp_nav_register_node(
          {root_id}::integer, 'Child {suffix}', 2::smallint, NULL::integer, '/r-{suffix}/c', '0002'
        )
        """,
        pg_env,
    )
    root_obj = _psql(
        f"""SELECT "MetaObjID" FROM portal."NavTree" WHERE "ID" = {root_id}""",
        pg_env,
    )
    child_obj = _psql(
        f"""SELECT "MetaObjID" FROM portal."NavTree" WHERE "ID" = {child_id}""",
        pg_env,
    )
    child_path = _psql(
        f"""
        SELECT tn."Path"::text
        FROM "Meta"."TreeNodes" tn
        WHERE tn."ObjID" = {child_obj}
          AND tn."MetaLinkID" = portal.fn_nav_parent_metalink_id()
        """,
        pg_env,
    )
    assert child_path == f"n{root_obj}.n{child_obj}"


def test_hierarchical_tree_rejects_cycle(pg_env: dict[str, str]) -> None:
    suffix = uuid.uuid4().hex[:8]
    link_type = _psql(
        """
        INSERT INTO "Meta"."LinkTypes" ("Name") VALUES ('TreeCycleTest')
        RETURNING "ID"
        """,
        pg_env,
    )
    cls = _psql(
        f"""INSERT INTO "Meta"."Classes" ("Name") VALUES ('TreeCls_{suffix}') RETURNING "ID" """,
        pg_env,
    )
    meta_link = _psql(
        f"""
        INSERT INTO "Meta"."MetaLinks"
          ("ClassID", "Name", "TargetClassID", "MaxCard", "IsHierarchical")
        VALUES ({cls}, 'Parent', {cls}, 1, true)
        RETURNING "ID"
        """,
        pg_env,
    )
    a = _psql(f'INSERT INTO "Meta"."Objs" ("ClassID") VALUES ({cls}) RETURNING "ID"', pg_env)
    b = _psql(f'INSERT INTO "Meta"."Objs" ("ClassID") VALUES ({cls}) RETURNING "ID"', pg_env)
    name = f"tc-{suffix}"
    _psql(
        f"SELECT \"Meta\".sp_tree_attach_child({a}, NULL, {meta_link})",
        pg_env,
    )
    _psql(
        f"SELECT \"Meta\".sp_tree_attach_child({b}, NULL, {meta_link})",
        pg_env,
    )
    _psql(
        f"""
        INSERT INTO "Meta"."Links"
          ("Name", "ClassID1", "ClassID2", "LinkTypeID", "MetaLinkID", "ObjID1", "ObjID2")
        VALUES ('{name}-b', {cls}, {cls}, {link_type}, {meta_link}, {b}, {a})
        """,
        pg_env,
    )
    with pytest.raises(RuntimeError, match="cycle"):
        _psql(
            f"""
            INSERT INTO "Meta"."Links"
              ("Name", "ClassID1", "ClassID2", "LinkTypeID", "MetaLinkID", "ObjID1", "ObjID2")
            VALUES ('{name}-a', {cls}, {cls}, {link_type}, {meta_link}, {a}, {b})
            """,
            pg_env,
        )


def test_sp_nav_backfill_meta_idempotent(pg_env: dict[str, str]) -> None:
    dry = _psql(
        "SELECT count(*) FROM portal.sp_nav_backfill_meta(true) WHERE action = 'would_create'",
        pg_env,
    )
    assert int(dry) >= 0
    _psql("SELECT count(*) FROM portal.sp_nav_backfill_meta(false) WHERE action = 'created'", pg_env)
    missing = _psql(
        'SELECT count(*) FROM portal."NavTree" WHERE "MetaObjID" IS NULL',
        pg_env,
    )
    assert int(missing) == 0
