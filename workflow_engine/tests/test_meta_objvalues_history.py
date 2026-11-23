"""Meta object history (H2): every object, value, link and scope change is kept in a ledger."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, LiteralString

import psycopg
import pytest

from goliath_app.portal.connection import build_portal_conninfo
from workflow_engine.tests.helpers.portal_session_test_helpers import (
    grant_organization_admin,
    grant_role_nav_tree,
    open_session_token,
)

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"
PORTAL_TEST_PASSWORD = "meta_history_test_pw"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    return env


def _conninfo(env: dict[str, str]) -> str:
    return (
        f"host={env['PGHOST']} port={env['PGPORT']} dbname={env['PGDATABASE']} "
        f"user={env['PGUSER']} password={env['PGPASSWORD']}"
    )


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
def history_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True, capture_output=True)
    escaped = PORTAL_TEST_PASSWORD.replace("'", "''")
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'", env)
    return env


def _one(conn: psycopg.Connection, sql: LiteralString, params: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return tuple(row)


def _class_id(conn: psycopg.Connection, name: str) -> int:
    return int(_one(conn, 'SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = %s', (name,))[0])


def _kinds(conn: psycopg.Connection, obj_id: int) -> list[str]:
    return [str(r[0]) for r in conn.execute(
        'SELECT "ChangeKind" FROM "Meta"."ObjValuesHistory" WHERE "ObjID" = %s ORDER BY "HistoryID"', (obj_id,)
    ).fetchall()]


def _new_obj(conn: psycopg.Connection, class_id: int, data: str) -> int:
    return int(_one(conn, 'SELECT "Meta".sp_obj_insert(%s, %s::jsonb)', (class_id, data))[0])


def _update(conn: psycopg.Connection, obj_id: int, data: str) -> None:
    conn.execute('SELECT "Meta".sp_obj_update(%s, %s::jsonb)', (obj_id, data))


def test_history_is_a_registered_ledger_and_verifies(history_env: dict[str, str]) -> None:
    with psycopg.connect(_conninfo(history_env), autocommit=True) as conn:
        assert _one(
            conn, "SELECT count(*) FROM portal.ledger_registry WHERE ledger_name = 'meta.obj_values_history'"
        )[0] == 1
        assert conn.execute("SELECT * FROM portal.fn_ledger_verify('meta.obj_values_history')").fetchall() == []


def test_lifecycle_is_recorded_with_actor_and_survives_delete(history_env: dict[str, str]) -> None:
    with psycopg.connect(_conninfo(history_env), autocommit=True) as conn:
        entity = _class_id(conn, "platform/Person")
        with conn.transaction():
            conn.execute("SELECT set_config('goliath.actor_user_id', '1', true)")
            obj_id = _new_obj(conn, entity, '{"Label": "History A"}')
        created = _kinds(conn, obj_id)
        assert created[0] == "object.create" and "values.insert" in created
        _update(conn, obj_id, '{"Label": "History A"}')
        assert _kinds(conn, obj_id) == created, "an update that changes nothing records nothing"
        _update(conn, obj_id, '{"Label": "History B"}')
        conn.execute('DELETE FROM "Meta"."Objs" WHERE "ID" = %s', (obj_id,))

        kinds = _kinds(conn, obj_id)
        assert kinds.count("values.update") == 1
        assert "object.delete" in kinds and "values.delete" in kinds
        before, after, actor = _one(
            conn,
            'SELECT "DataBefore", "DataAfter", "ActorUserID" FROM "Meta"."ObjValuesHistory" '
            "WHERE \"ObjID\" = %s AND \"ChangeKind\" = 'values.update'",
            (obj_id,),
        )
        assert before["Label"] == "History A" and after["Label"] == "History B"
        assert actor is None
        first_actor = _one(
            conn,
            'SELECT "ActorUserID" FROM "Meta"."ObjValuesHistory" '
            "WHERE \"ObjID\" = %s AND \"ChangeKind\" = 'object.create'",
            (obj_id,),
        )[0]
        assert first_actor == 1
        assert conn.execute("SELECT * FROM portal.fn_ledger_verify('meta.obj_values_history')").fetchall() == []


def test_as_of_reads_past_values(history_env: dict[str, str]) -> None:
    with psycopg.connect(_conninfo(history_env), autocommit=True) as conn:
        entity = _class_id(conn, "platform/Person")
        obj_id = _new_obj(conn, entity, '{"Label": "v1"}')
        t1 = _one(conn, "SELECT clock_timestamp()")[0]
        time.sleep(0.05)
        _update(conn, obj_id, '{"Label": "v2"}')
        t2 = _one(conn, "SELECT clock_timestamp()")[0]
        time.sleep(0.05)
        conn.execute('DELETE FROM "Meta"."Objs" WHERE "ID" = %s', (obj_id,))

        assert _one(conn, 'SELECT "Meta".fn_merged_obj_document_as_of(%s, %s)', (obj_id, t1))[0] ["Label"] == "v1"
        assert _one(conn, 'SELECT "Meta".fn_merged_obj_document_as_of(%s, %s)', (obj_id, t2))[0] ["Label"] == "v2"
        assert _one(conn, 'SELECT "Meta".fn_merged_obj_document_as_of(%s, now())', (obj_id,))[0] == {}


def test_history_rows_cannot_be_edited(history_env: dict[str, str]) -> None:
    with psycopg.connect(_conninfo(history_env), autocommit=True) as conn:
        entity = _class_id(conn, "platform/Person")
        obj_id = _new_obj(conn, entity, '{"Label": "immutable"}')
        with pytest.raises(psycopg.Error):
            conn.execute(
                'UPDATE "Meta"."ObjValuesHistory" SET "DataAfter" = NULL WHERE "ObjID" = %s', (obj_id,)
            )
        with pytest.raises(psycopg.Error):
            conn.execute('DELETE FROM "Meta"."ObjValuesHistory" WHERE "ObjID" = %s', (obj_id,))


def test_raw_history_readers_are_not_public(history_env: dict[str, str]) -> None:
    with psycopg.connect(_conninfo(history_env), autocommit=True) as conn:
        for fn in ("fn_obj_history(integer)", "fn_obj_values_as_of(integer,timestamp with time zone)"):
            granted = _one(
                conn, "SELECT has_function_privilege('goliath_portal', %s, 'EXECUTE')", (f'"Meta".{fn}',)
            )[0]
            assert granted is False


def test_session_writes_are_attributed_and_history_is_scoped(history_env: dict[str, str]) -> None:
    env = history_env
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    psql = lambda sql: _psql(sql, env)  # noqa: E731
    user_id = int(psql(
        f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('History Admin', 'hist-{uuid.uuid4().hex[:8]}@test', 1) RETURNING "ID" """
    ))
    org = psql(f"SELECT * FROM portal.sp_organization_create('HistOrg-{user_id}')")
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)], env=env, check=True)
    grant_organization_admin(psql, org_id, user_id)
    role_name = f"hist_{uuid.uuid4().hex[:8]}"
    role_id = int(psql(f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope") VALUES ('{role_name}', false) RETURNING "ID" """))
    for perm in ("meta.schema.read", "meta.object.read", "meta.object.write"):
        psql(
            f"""INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
                SELECT {role_id}, "ID" FROM "RBAC"."Permissions" WHERE "Name" = '{perm}' LIMIT 1"""
        )
    psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'SCOPED', {scope_id}, true, now() AT TIME ZONE 'utc')"""
    )
    grant_role_nav_tree(psql, role_id, scope_id)
    token = open_session_token(psql, user_id, scope_id=scope_id, role_id=role_id)

    with psycopg.connect(build_portal_conninfo(), autocommit=True) as conn:
        obj_id = int(_one(
            conn, "SELECT portal.sp_session_meta_obj_insert(%s, %s, %s::jsonb)",
            (token, "platform/Person", '{"Label": "Attributed"}'),
        )[0])
        conn.execute(
            "SELECT portal.sp_session_meta_obj_update(%s, %s, %s::jsonb)",
            (token, obj_id, '{"Label": "Attributed 2"}'),
        )
        rows = conn.execute(
            "SELECT change_kind, actor_user_id FROM portal.sp_session_meta_obj_history(%s, %s)", (token, obj_id)
        ).fetchall()
    kinds = [r[0] for r in rows]
    assert "object.create" in kinds and "values.update" in kinds and "object.scope" in kinds
    assert {r[1] for r in rows if r[0] in ("object.create", "values.update")} == {user_id}

    psql(f'DELETE FROM "Meta"."Objs" WHERE "ID" = {obj_id}')
    with psycopg.connect(build_portal_conninfo(), autocommit=True) as conn:
        kinds_after = [r[0] for r in conn.execute(
            "SELECT change_kind FROM portal.sp_session_meta_obj_history(%s, %s)", (token, obj_id)
        ).fetchall()]
        assert "object.delete" in kinds_after

        other = int(psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Other', 'other-{uuid.uuid4().hex[:8]}@test', 1) RETURNING "ID" """
        ))
        other_org = psql(f"SELECT * FROM portal.sp_organization_create('OtherHist-{other}')")
        other_scope = int(other_org.split("|")[1])
        psql(
            f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
                VALUES ({other}, {role_id}, 'SCOPED', {other_scope}, true, now() AT TIME ZONE 'utc')"""
        )
        grant_role_nav_tree(psql, role_id, other_scope)
        other_token = open_session_token(psql, other, scope_id=other_scope, role_id=role_id)
        with pytest.raises(psycopg.Error):
            conn.execute("SELECT * FROM portal.sp_session_meta_obj_history(%s, %s)", (other_token, obj_id))
