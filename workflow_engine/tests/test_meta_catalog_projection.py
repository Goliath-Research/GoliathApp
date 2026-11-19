"""Catalogs as Meta classes (meta_catalog_projection.sql, semantic_catalog_meta.sql)."""

from __future__ import annotations

import json
import uuid

from workflow_engine.tests.test_portal_record_editors import _lit, _psql, editor_env  # noqa: F401


def _kind(env: dict[str, str]) -> dict[str, str]:
    """A scratch catalog table bound to its own class: serial key, defaults, jsonb, arrays, regtype."""
    tag = "cat" + uuid.uuid4().hex[:8]
    table = f"public.{tag}"
    _psql(
        f"""CREATE TABLE {table} (
              id serial PRIMARY KEY,
              code text NOT NULL UNIQUE,
              doc jsonb NOT NULL DEFAULT '{{}}',
              tags text[] NOT NULL DEFAULT '{{}}',
              note text,
              row_type regtype,
              created_at_utc timestamptz NOT NULL DEFAULT now()
            );
            CREATE TABLE {table}_child (
              id serial PRIMARY KEY,
              parent_id integer NOT NULL REFERENCES {table}(id) ON DELETE CASCADE,
              name text NOT NULL
            )""",
        env,
    )
    _psql(
        f"""SELECT "Meta".sp_catalog_register_kind('{tag}', '{tag}/Thing', 'platform/Entity', '{table}', ARRAY['id'], ARRAY['code']);
            SELECT "Meta".sp_catalog_register_kind('{tag}.child', '{tag}/Child', 'platform/Entity', '{table}_child', ARRAY['id'], ARRAY['name'])""",
        env,
    )
    return {"tag": tag, "table": table, "child": f"{table}_child"}


def _obj(env: dict[str, str], kind: str, key: dict) -> str:
    return _psql(
        f"""SELECT obj_id FROM "Meta".catalog_row WHERE kind = {_lit(kind)} AND row_key = {_lit(json.dumps(key))}::jsonb""",
        env,
    )


def _doc(env: dict[str, str], obj: str) -> dict:
    return json.loads(_psql(f'SELECT "Meta".fn_merged_obj_document({obj})', env))


def _drift(env: dict[str, str], kind: str) -> str:
    return _psql(f"""SELECT count(*) FROM "Meta".fn_catalog_drift({_lit(kind)})""", env)


def test_register_builds_typed_fields_from_columns(editor_env: dict[str, str]) -> None:
    env = editor_env
    k = _kind(env)
    rows = _psql(
        f"""SELECT f."Name" || ':' || t.name || ':' || f."Required"
            FROM "Meta"."Fields" f JOIN "Meta"."Classes" c ON c."ID" = f."ClassID" JOIN wf.data_type t ON t.id = f."TypeID"
            WHERE c."Name" = '{k['tag']}/Thing' ORDER BY f."Name" """,
        env,
    ).splitlines()
    assert rows == [
        "Label:platform/catalog/Text:true",
        "code:platform/catalog/Text:true",
        "created_at_utc:platform/catalog/Timestamp:false",
        "doc:platform/catalog/Document:false",
        "id:platform/catalog/Integer:false",
        "note:platform/catalog/Text:false",
        "row_type:platform/catalog/Text:false",
        "tags:platform/catalog/TextList:false",
    ]


def test_table_writes_keep_meta_in_step(editor_env: dict[str, str]) -> None:
    env = editor_env
    k = _kind(env)
    rid = _psql(
        f"""INSERT INTO {k['table']} (code, doc, tags, row_type) VALUES ('a', '{{"x": null, "y": [1]}}', ARRAY['t1'], 'portal.inv_stock_lot_row')
            RETURNING id""",
        env,
    )
    obj = _obj(env, k["tag"], {"id": int(rid)})
    doc = _doc(env, obj)
    assert doc["code"] == "a" and doc["Label"] == "a"
    assert doc["doc"] == {"x": None, "y": [1]}  # nested nulls kept
    assert doc["tags"] == ["t1"] and doc["row_type"] == "portal.inv_stock_lot_row"
    assert "note" not in doc

    _psql(f"UPDATE {k['table']} SET note = 'n', code = 'b' WHERE id = {rid}", env)
    doc = _doc(env, obj)
    assert doc["note"] == "n" and doc["Label"] == "b"
    assert _drift(env, k["tag"]) == "0"

    _psql(f"DELETE FROM {k['table']} WHERE id = {rid}", env)
    assert _psql(f'SELECT count(*) FROM "Meta"."Objs" WHERE "ID" = {obj}', env) == "0"
    assert _drift(env, k["tag"]) == "0"


def test_meta_writes_project_to_the_table(editor_env: dict[str, str]) -> None:
    env = editor_env
    k = _kind(env)
    cls = _psql(f"""SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = '{k['tag']}/Thing'""", env)
    obj = _psql(f"""SELECT "Meta".sp_obj_insert({cls}, '{{"Label": "new", "code": "new", "tags": ["a", "b"]}}')""", env)
    row = json.loads(_psql(f"SELECT to_jsonb(t) FROM {k['table']} t WHERE code = 'new'", env))
    assert row["tags"] == ["a", "b"] and row["doc"] == {}
    doc = _doc(env, obj)
    assert doc["id"] == row["id"] and "created_at_utc" in doc  # table-assigned values written back

    edited = dict(doc, note="edited")
    _psql(f"""SELECT "Meta".sp_obj_update({obj}, {_lit(json.dumps(edited))}::jsonb)""", env)
    assert _psql(f"SELECT note FROM {k['table']} WHERE id = {row['id']}", env) == "edited"

    edited.pop("note")
    _psql(f"""SELECT "Meta".sp_obj_update({obj}, {_lit(json.dumps(edited))}::jsonb)""", env)
    assert _psql(f"SELECT note IS NULL FROM {k['table']} WHERE id = {row['id']}", env) == "t"
    assert _drift(env, k["tag"]) == "0"

    child = _psql(f"INSERT INTO {k['child']} (parent_id, name) VALUES ({row['id']}, 'c') RETURNING id", env)
    child_obj = _obj(env, f"{k['tag']}.child", {"id": int(child)})
    _psql(f'DELETE FROM "Meta"."Objs" WHERE "ID" = {obj}', env)
    assert _psql(f"SELECT count(*) FROM {k['table']} WHERE id = {row['id']}", env) == "0"
    # The table cascade removed the child row; its object goes with it.
    assert _psql(f'SELECT count(*) FROM "Meta"."Objs" WHERE "ID" = {child_obj}', env) == "0"
    assert _drift(env, k["tag"]) == "0" and _drift(env, f"{k['tag']}.child") == "0"


def test_drift_is_reported_and_meta_wins_on_repair(editor_env: dict[str, str]) -> None:
    env = editor_env
    k = _kind(env)
    rid = _psql(f"INSERT INTO {k['table']} (code) VALUES ('d') RETURNING id", env)
    # A write that bypasses the trigger (e.g. replication or a disabled trigger) leaves drift.
    _psql(
        f"""SET session_replication_role = replica; UPDATE {k['table']} SET code = 'changed' WHERE id = {rid};
            SET session_replication_role = origin""",
        env,
    )
    assert _psql(f"""SELECT issue FROM "Meta".fn_catalog_drift({_lit(k['tag'])})""", env) == "differs"
    assert _psql(f"""SELECT "Meta".sp_catalog_project_all({_lit(k['tag'])})""", env) == "1"
    assert _psql(f"SELECT code FROM {k['table']} WHERE id = {rid}", env) == "d"
    assert _drift(env, k["tag"]) == "0"


def test_migrate_is_idempotent_and_values_do_not_depend_on_session(editor_env: dict[str, str]) -> None:
    env = editor_env
    k = _kind(env)
    _psql(
        f"""SET TimeZone = 'America/New_York'; SET search_path = public, portal;
            INSERT INTO {k['table']} (code, row_type) VALUES ('tz', 'inv_stock_lot_row')""",
        env,
    )
    first = _psql(f"""SELECT table_rows || '/' || objects FROM "Meta".sp_catalog_migrate({_lit(k['tag'])})""", env)
    second = _psql(f"""SELECT table_rows || '/' || objects FROM "Meta".sp_catalog_migrate({_lit(k['tag'])})""", env)
    assert first == second == "1/1"
    obj = _psql(f"""SELECT obj_id FROM "Meta".catalog_row WHERE kind = {_lit(k['tag'])}""", env)
    doc = _doc(env, obj)
    assert doc["row_type"] == "portal.inv_stock_lot_row"
    assert doc["created_at_utc"].endswith("+00:00")
    assert _drift(env, k["tag"]) == "0"


def test_semantic_catalog_is_in_meta(editor_env: dict[str, str]) -> None:
    env = editor_env
    kinds = _psql("""SELECT kind FROM "Meta".catalog_kind WHERE kind LIKE 'semantic.%'""", env).splitlines()
    assert sorted(kinds) == sorted(
        ["semantic.action_binding", "semantic.attribute", "semantic.entity", "semantic.nav_binding", "semantic.namespace", "semantic.request"]
    )
    for rel, kind in (
        ("portal.semantic_namespace", "semantic.namespace"),
        ("portal.semantic_entity", "semantic.entity"),
        ("portal.semantic_attribute", "semantic.attribute"),
        ("portal.semantic_request", "semantic.request"),
        ("portal.semantic_action_binding", "semantic.action_binding"),
    ):
        assert _psql(f"SELECT count(*) FROM {rel}", env) == _psql(
            f"""SELECT count(*) FROM "Meta".catalog_row WHERE kind = '{kind}'""", env
        )
    # The official register procedure still works and lands in Meta.
    ns = "catns" + uuid.uuid4().hex[:6]
    _psql(f"CALL portal.sp_semantic_register_entity({_lit(ns)}, 'thing', 'Thing', '', 's', '1', '', NULL, NULL)", env)
    eid = _psql(f"SELECT id FROM portal.semantic_entity WHERE namespace = {_lit(ns)}", env)
    obj = _obj(env, "semantic.entity", {"id": int(eid)})
    assert _doc(env, obj)["Label"] == f"{ns} thing"
    assert _psql("""SELECT count(*) FROM "Meta".fn_catalog_drift() WHERE kind LIKE 'semantic.%'""", env) == "0"
