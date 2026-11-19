"""Meta model record editors (portal_session_meta_editors_api.sql)."""

from __future__ import annotations

import json
import uuid

import pytest

from workflow_engine.tests.test_portal_record_editors import (  # noqa: F401  (pytest fixtures)
    _any_data_type,
    _lit,
    _psql,
    author_token,
    editor_env,
    reader_token,
)


def test_meta_editor_functions_executable_by_portal(editor_env: dict[str, str]) -> None:
    missing = _psql(
        """
        SELECT string_agg(p.oid::regprocedure::text, ', ')
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'portal'
          AND p.proname LIKE 'sp\\_session\\_meta\\_editor\\_%'
          AND NOT has_function_privilege('goliath_portal', p.oid, 'EXECUTE')
        """,
        editor_env,
    )
    assert missing == ""


def test_platform_classes_require_god_architect(editor_env: dict[str, str], author_token: str) -> None:
    tok = _lit(author_token)
    type_id = _any_data_type(editor_env)
    with pytest.raises(RuntimeError, match="GS403|god|architect|denied"):
        _psql(
            f"SELECT portal.sp_session_meta_editor_save_class({tok}, NULL, "
            f"{_lit({'class_name': f'platform/Blocked{uuid.uuid4().hex[:6]}', 'parent_class_name': 'platform/Entity'})}::jsonb)",
            editor_env,
        )
    with pytest.raises(RuntimeError, match="GS403|god|architect|denied"):
        _psql(
            f"SELECT portal.sp_session_meta_editor_save_field({tok}, NULL, "
            f"{_lit({'class_name': 'platform/Entity', 'field_name': 'Blocked', 'type_id': type_id})}::jsonb)",
            editor_env,
        )
    with pytest.raises(RuntimeError, match="GS403|god|architect|denied"):
        _psql(f"SELECT * FROM portal.sp_session_meta_field_retire({tok}, 'platform/Entity', 'Nope')", editor_env)


def test_meta_writers_require_model_author(editor_env: dict[str, str], reader_token: str) -> None:
    with pytest.raises(RuntimeError, match="model author permission denied"):
        _psql(
            f"SELECT portal.sp_session_meta_editor_save_class({_lit(reader_token)}, NULL, "
            f"{_lit({'class_name': 'your_app/Denied', 'parent_class_name': 'platform/Entity'})}::jsonb)",
            editor_env,
        )


def test_class_field_relation_lifecycle(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    tok = _lit(author_token)
    suffix = uuid.uuid4().hex[:6]
    base, child = f"your_app/MetaEdBase{suffix}", f"your_app/MetaEdChild{suffix}"
    type_id = _any_data_type(env)

    for name, parent in ((base, "platform/Entity"), (child, base)):
        assert _psql(
            f"SELECT portal.sp_session_meta_editor_save_class({tok}, NULL, "
            f"{_lit({'class_name': name, 'parent_class_name': parent})}::jsonb)",
            env,
        ) == name
    with pytest.raises(RuntimeError, match="namespace/ClassName"):
        _psql(
            f"SELECT portal.sp_session_meta_editor_save_class({tok}, NULL, "
            f"{_lit({'class_name': 'bad name', 'parent_class_name': base})}::jsonb)",
            env,
        )
    _psql(f"SELECT portal.sp_session_meta_editor_save_class({tok}, {_lit(base)}, {_lit({'is_abstract': True})}::jsonb)", env)
    doc = json.loads(_psql(f"SELECT portal.sp_session_meta_editor_get_class({tok}, {_lit(base)})", env))
    assert doc["is_abstract"] is True and doc["parent_class_name"] == "platform/Entity"

    field_id = int(
        _psql(
            f"SELECT portal.sp_session_meta_editor_save_field({tok}, NULL, "
            f"{_lit({'class_name': base, 'field_name': 'Label', 'type_id': type_id, 'description': 'Shown name'})}::jsonb)",
            env,
        )
    )
    # No shadowing along the inheritance line.
    with pytest.raises(RuntimeError, match="already exists"):
        _psql(
            f"SELECT portal.sp_session_meta_editor_save_field({tok}, NULL, "
            f"{_lit({'class_name': child, 'field_name': 'Label', 'type_id': type_id})}::jsonb)",
            env,
        )
    _psql(
        f"SELECT portal.sp_session_meta_editor_save_field({tok}, {field_id}, "
        f"{_lit({'type_id': type_id, 'required': True})}::jsonb)",
        env,
    )
    assert _psql(f'SELECT "Required" FROM "Meta"."Fields" WHERE "ID" = {field_id}', env) == "t"

    link_id = int(
        _psql(
            f"SELECT portal.sp_session_meta_editor_save_link({tok}, NULL, {_lit({
                'class_name': child, 'link_name': 'Parent', 'target_class_name': base,
                'min_card': 0, 'max_card': 1,
            })}::jsonb)",
            env,
        )
    )
    with pytest.raises(RuntimeError, match="cardinality"):
        _psql(
            f"SELECT portal.sp_session_meta_editor_save_link({tok}, {link_id}, "
            f"{_lit({'min_card': 2, 'max_card': 1})}::jsonb)",
            env,
        )

    # Deletes are refused while something still depends on the class.
    with pytest.raises(RuntimeError, match="subclasses"):
        _psql(f"SELECT portal.sp_session_meta_editor_delete_class({tok}, {_lit(base)})", env)
    with pytest.raises(RuntimeError, match="fields, methods or relations"):
        _psql(f"SELECT portal.sp_session_meta_editor_delete_class({tok}, {_lit(child)})", env)

    assert _psql(f"SELECT portal.sp_session_meta_editor_delete_link({tok}, {link_id})", env) == "deleted"
    assert _psql(f"SELECT portal.sp_session_meta_editor_delete_class({tok}, {_lit(child)})", env) == "deleted"
    assert _psql(f"SELECT portal.sp_session_meta_editor_delete_field({tok}, {field_id})", env) == "deleted"
    assert _psql(f"SELECT portal.sp_session_meta_editor_delete_class({tok}, {_lit(base)})", env) == "deleted"
    assert _psql(
        f"""SELECT count(*) FROM "Meta"."Classes" WHERE "Name" IN ({_lit(base)}, {_lit(child)})""", env
    ) == "0"
    assert _psql(
        "SELECT count(*) FROM pg_views WHERE schemaname = 'Meta' "
        f"AND viewname IN ({_lit('V' + base)}, {_lit('V' + child)})",
        env,
    ) == "0"
    audit = _psql(
        "SELECT string_agg(DISTINCT entity, ',' ORDER BY entity) FROM portal.record_editor_audit "
        f"WHERE entity LIKE 'meta%' AND record_key IN ({_lit(base)}, {_lit(child)}, {_lit(str(field_id))}, {_lit(str(link_id))})",
        env,
    )
    assert audit == "meta_class,meta_field,meta_link"


def test_field_with_values_is_not_deleted(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    tok = _lit(author_token)
    cls = f"your_app/MetaEdValues{uuid.uuid4().hex[:6]}"
    type_id = _any_data_type(env)
    _psql(
        f"SELECT portal.sp_session_meta_editor_save_class({tok}, NULL, "
        f"{_lit({'class_name': cls, 'parent_class_name': 'platform/Entity'})}::jsonb)",
        env,
    )
    field_id = int(
        _psql(
            f"SELECT portal.sp_session_meta_editor_save_field({tok}, NULL, "
            f"{_lit({'class_name': cls, 'field_name': 'Note', 'type_id': type_id})}::jsonb)",
            env,
        )
    )
    obj = _psql(f"""INSERT INTO "Meta"."Objs" ("ClassID") SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = {_lit(cls)} RETURNING "ID" """, env)
    _psql(
        f"""INSERT INTO "Meta"."ObjValues" ("ObjID", "ClassID", "Data")
            SELECT {obj}, "ID", '{{"Note": "kept"}}'::jsonb FROM "Meta"."Classes" WHERE "Name" = {_lit(cls)}""",
        env,
    )
    with pytest.raises(RuntimeError, match="objects hold values"):
        _psql(f"SELECT portal.sp_session_meta_editor_delete_field({tok}, {field_id})", env)
    with pytest.raises(RuntimeError, match="has objects"):
        _psql(f"SELECT portal.sp_session_meta_editor_save_class({tok}, {_lit(cls)}, {_lit({'is_abstract': True})}::jsonb)", env)
