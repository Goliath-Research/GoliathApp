"""Generic Meta tree editor (portal_session_meta_tree_api.sql) and the NavTree projection."""

from __future__ import annotations

import uuid

import pytest

from workflow_engine.tests.test_portal_record_editors import (  # noqa: F401  (pytest fixtures)
    _lit,
    _psql,
    author_token,
    editor_env,
    reader_token,
)


def _tree_class(env: dict[str, str], token: str) -> tuple[str, list[int]]:
    name = f"your_app/TreeEd{uuid.uuid4().hex[:6]}"
    _psql(f"SELECT * FROM portal.sp_session_meta_class_create({_lit(token)}, {_lit(name)}, 'platform/Person')", env)
    cls = _psql(f'SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = {_lit(name)}', env)
    _psql(
        f"""INSERT INTO "Meta"."MetaLinks" ("ClassID", "Name", "TargetClassID", "MaxCard", "IsHierarchical")
            VALUES ({cls}, 'Parent', {cls}, 1, true)""",
        env,
    )
    objs = [
        int(_psql(f"""SELECT "Meta".sp_obj_insert({cls}, {_lit({"Label": label})}::jsonb)""", env))
        for label in ("a", "b", "c", "d")
    ]
    return name, objs


def _tree(env: dict[str, str], token: str, name: str) -> dict[str, tuple[str, int]]:
    rows = _psql(
        f"SELECT display_label, COALESCE(parent_obj_id::text, ''), COALESCE(seq, 0) "
        f"FROM portal.sp_session_meta_tree_list({_lit(token)}, {_lit(name)})",
        env,
    )
    out: dict[str, tuple[str, int]] = {}
    for line in rows.splitlines():
        label, parent, seq = line.split("|")
        out[label] = (parent, int(seq))
    return out


def test_tree_functions_executable_by_portal(editor_env: dict[str, str]) -> None:
    missing = _psql(
        """
        SELECT string_agg(p.oid::regprocedure::text, ', ')
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'portal' AND p.proname LIKE 'sp\\_session\\_meta\\_tree\\_%'
          AND NOT has_function_privilege('goliath_portal', p.oid, 'EXECUTE')
        """,
        editor_env,
    )
    assert missing == ""


def test_tree_classes_lists_navnode(editor_env: dict[str, str], author_token: str) -> None:
    names = _psql(f"SELECT class_name FROM portal.sp_session_meta_tree_classes({_lit(author_token)})", editor_env)
    assert "portal/NavNode" in names.splitlines()


def test_move_reorder_cycle_and_delete(editor_env: dict[str, str], author_token: str) -> None:
    env, tok = editor_env, _lit(author_token)
    name, (a, b, c, d) = _tree_class(env, author_token)
    move = f"SELECT portal.sp_session_meta_tree_move({tok}, {_lit(name)}, %s, %s, %s)"

    _psql(move % (b, a, "NULL"), env)
    _psql(move % (c, a, "NULL"), env)
    _psql(move % (d, a, 0), env)  # first child
    tree = _tree(env, author_token, name)
    assert tree["b"][0] == tree["c"][0] == tree["d"][0] == str(a)
    assert tree["d"][1] < tree["b"][1] < tree["c"][1]

    _psql(move % (c, a, 0), env)  # reorder: c to the top
    tree = _tree(env, author_token, name)
    assert tree["c"][1] < tree["d"][1] < tree["b"][1]

    _psql(move % (d, b, "NULL"), env)  # reparent d under b
    assert _tree(env, author_token, name)["d"][0] == str(b)

    with pytest.raises(RuntimeError, match="descendant"):
        _psql(move % (a, d, "NULL"), env)  # a under its grandchild

    _psql(move % (d, "NULL", "NULL"), env)  # back to root
    assert _tree(env, author_token, name)["d"][0] == ""

    delete = f"SELECT portal.sp_session_meta_tree_delete({tok}, {_lit(name)}, %s)"
    with pytest.raises(RuntimeError, match="has children"):
        _psql(delete % a, env)
    assert _psql(delete % c, env) == "deleted"
    assert "c" not in _tree(env, author_token, name)
    audit = _psql(
        "SELECT count(*) FROM portal.record_editor_audit WHERE entity = 'meta_tree' "
        f"AND record_key IN ('{b}', '{c}', '{d}')",
        env,
    )
    assert int(audit) >= 5


def test_platform_trees_require_god_architect(editor_env: dict[str, str], author_token: str) -> None:
    obj = _psql(
        "SELECT \"MetaObjID\" FROM portal.\"NavTree\" WHERE \"MetaObjID\" IS NOT NULL ORDER BY \"ID\" DESC LIMIT 1",
        editor_env,
    )
    if not obj:
        pytest.skip("no nav nodes")
    with pytest.raises(RuntimeError, match="GS403|god|architect|denied"):
        _psql(
            f"SELECT portal.sp_session_meta_tree_move({_lit(author_token)}, 'portal/NavNode', {obj}, NULL, NULL)",
            editor_env,
        )


def test_tree_writes_require_model_author(editor_env: dict[str, str], author_token: str, reader_token: str) -> None:
    name, (a, b, _c, _d) = _tree_class(editor_env, author_token)
    with pytest.raises(RuntimeError, match="model author permission denied"):
        _psql(
            f"SELECT portal.sp_session_meta_tree_move({_lit(reader_token)}, {_lit(name)}, {b}, {a}, NULL)",
            editor_env,
        )


def test_navtree_follows_meta_tree(editor_env: dict[str, str]) -> None:
    """Moving or renaming a NavNode in the Meta tree updates the portal.NavTree menu row."""
    env = editor_env
    row = _psql(
        """SELECT n."ID", n."MetaObjID", n."Seq", n."Caption" FROM portal."NavTree" n
           JOIN "Meta"."TreeNodes" tn ON tn."ObjID" = n."MetaObjID" AND tn."MetaLinkID" = portal.fn_nav_parent_metalink_id()
           WHERE n."ParentID" IS NOT NULL ORDER BY n."ID" DESC LIMIT 1""",
        env,
    )
    if not row:
        pytest.skip("no nav nodes")
    nav_id, obj, seq, caption = row.split("|")
    link = "portal.fn_nav_parent_metalink_id()"
    try:
        _psql(f'UPDATE "Meta"."TreeNodes" SET "Seq" = 777 WHERE "ObjID" = {obj} AND "MetaLinkID" = {link}', env)
        assert _psql(f'SELECT "Seq" FROM portal."NavTree" WHERE "ID" = {nav_id}', env) == "777"
        _psql(
            f"""UPDATE "Meta"."ObjValues" SET "Data" = jsonb_set("Data", '{{Caption}}', '"Renamed"')
                WHERE "ObjID" = {obj} AND "Data" ? 'Caption'""",
            env,
        )
        assert _psql(f'SELECT "Caption" FROM portal."NavTree" WHERE "ID" = {nav_id}', env) == "Renamed"
    finally:
        _psql(f'UPDATE "Meta"."TreeNodes" SET "Seq" = {seq} WHERE "ObjID" = {obj} AND "MetaLinkID" = {link}', env)
        _psql(
            f"""UPDATE "Meta"."ObjValues" SET "Data" = jsonb_set("Data", '{{Caption}}', to_jsonb({_lit(caption)}::text))
                WHERE "ObjID" = {obj} AND "Data" ? 'Caption'""",
            env,
        )
    assert _psql(f'SELECT "Caption" FROM portal."NavTree" WHERE "ID" = {nav_id}', env) == caption
