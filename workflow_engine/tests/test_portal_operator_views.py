"""Operator view/dashboard session API contracts."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest

from goliath_app.portal.connection import build_portal_conninfo
from workflow_engine.tests.helpers.portal_session_test_helpers import (
    create_org_with_admin,
    open_session_token,
)

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
SEED_SEMANTIC = SQL_PG / "seed_semantic_catalog.py"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    if env.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath"))
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
def portal_views_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    for _ in range(2):
        subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    subprocess.run(["python3", str(SEED_SEMANTIC)], env=env, check=True)
    return env


def _session(env: dict[str, str]) -> str:
    email = f"op-view-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Operator View User', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )
    _org_id, scope_id = create_org_with_admin(lambda sql: _psql(sql, env), user_id, f"Org-{user_id}")
    return open_session_token(lambda sql: _psql(sql, env), user_id, scope_id=scope_id)


def test_operator_view_dashboard_meta_and_crud(portal_views_env: dict[str, str]) -> None:
    token = _session(portal_views_env)
    conninfo = build_portal_conninfo()
    params = json.dumps(
        {
            "columns": [{"field": "name", "label": "Name"}],
            "filters": [],
            "sort": [],
            "groupBy": [],
            "aggregations": [],
            "limit": 10,
            "visualization": {"type": "table"},
        }
    )
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            """
            SELECT view_id FROM portal.sp_session_upsert_operator_view(
              %s, NULL, 'SQL Test View', 'desc',
              'core.list_organizations', '1', NULL, %s::jsonb, 'scope'
            )
            """,
            (token, params),
        ).fetchone()
        assert row is not None
        view_id = int(row[0])

        listed = conn.execute(
            "SELECT title, meta_obj_id FROM portal.sp_session_list_operator_views(%s)",
            (token,),
        ).fetchall()
        assert any(r[0] == "SQL Test View" and r[1] is not None for r in listed)

        fetched = conn.execute(
            "SELECT title FROM portal.sp_session_get_operator_view(%s, %s)",
            (token, view_id),
        ).fetchone()
        assert fetched is not None
        assert fetched[0] == "SQL Test View"

        dash = conn.execute(
            """
            SELECT dashboard_id FROM portal.sp_session_upsert_operator_dashboard(
              %s, NULL, 'SQL Dash', '', '{}'::jsonb, 'scope'
            )
            """,
            (token,),
        ).fetchone()
        assert dash is not None
        dashboard_id = int(dash[0])

        widgets = json.dumps(
            [
                {
                    "view_id": view_id,
                    "sort_order": 10,
                    "column_span": 1,
                    "grid_x": 0,
                    "grid_y": 0,
                    "grid_w": 6,
                    "grid_h": 2,
                    "widget_title": "Widget",
                    "viz_override": {"type": "bar"},
                }
            ]
        )
        cnt = conn.execute(
            "SELECT widget_count FROM portal.sp_session_set_dashboard_widgets(%s, %s, %s::jsonb)",
            (token, dashboard_id, widgets),
        ).fetchone()
        assert cnt is not None
        assert int(cnt[0]) == 1

        wrows = conn.execute(
            "SELECT grid_w, widget_title FROM portal.sp_session_list_dashboard_widgets(%s, %s)",
            (token, dashboard_id),
        ).fetchall()
        assert wrows[0][0] == 6
        assert wrows[0][1] == "Widget"

        deleted = conn.execute(
            "SELECT deleted FROM portal.sp_session_delete_operator_view(%s, %s)",
            (token, view_id),
        ).fetchone()
        assert deleted is not None
        assert deleted[0] is True

        class_row = conn.execute(
            """SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = 'platform/OperatorView'"""
        ).fetchone()
        assert class_row is not None


def test_private_operator_view_meta_redacts_definition(
    portal_views_env: dict[str, str],
) -> None:
    token = _session(portal_views_env)
    conninfo = build_portal_conninfo()
    params = json.dumps(
        {
            "columns": [{"field": "secret", "label": "Secret"}],
            "filters": [{"field": "id", "op": "eq", "value": 1}],
            "sort": [],
            "groupBy": [],
            "aggregations": [],
            "limit": 5,
            "visualization": {"type": "table"},
        }
    )
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            """
            SELECT view_id FROM portal.sp_session_upsert_operator_view(
              %s, NULL, 'Private SQL View', 'private',
              'core.list_organizations', '1', NULL, %s::jsonb, 'private'
            )
            """,
            (token, params),
        ).fetchone()
        assert row is not None
        view_id = int(row[0])

        meta_row = conn.execute(
            """
            SELECT m.meta_obj_id
            FROM portal.operator_view_meta_map m
            WHERE m.legacy_view_id = %s
            """,
            (view_id,),
        ).fetchone()
        assert meta_row is not None
        meta_obj_id = int(meta_row[0])

        doc_row = conn.execute(
            """
            SELECT ov."Data"->>'DefinitionJson',
                   ov."Data"->>'SemanticRequestCode'
            FROM "Meta"."ObjValues" ov
            WHERE ov."ObjID" = %s
            ORDER BY ov."ClassID"
            LIMIT 1
            """,
            (meta_obj_id,),
        ).fetchone()
        assert doc_row is not None
        assert doc_row[0] == "{}"
        assert doc_row[1] is None
