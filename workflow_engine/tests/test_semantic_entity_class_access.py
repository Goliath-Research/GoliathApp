"""Class read access for semantic entities mapped to Meta classes (semantic_entity_class_access.sql)."""

from __future__ import annotations

import uuid

from workflow_engine.tests.test_portal_record_editors import _lit, _make_user, _psql, editor_env  # noqa: F401


def _setup(env: dict[str, str]) -> dict[str, object]:
    ns = "acc" + uuid.uuid4().hex[:8]
    perm = "meta.schema.read"  # held by the test role only; it has no global meta.object.read
    user_id, _org, scope_id = _make_user(env, "Acc")
    role_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope") VALUES ('{ns}_role', false) RETURNING "ID" """,
            env,
        )
    )
    _psql(
        f"""INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
            SELECT {role_id}, "ID" FROM "RBAC"."Permissions" WHERE "Name" = {_lit(perm)}""",
        env,
    )
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'DIRECT', {scope_id}, true, now())""",
        env,
    )
    class_id = int(
        _psql(
            f"""INSERT INTO "Meta"."Classes" ("Name", "ParentID")
                SELECT '{ns}/Thing', "ID" FROM "Meta"."Classes" WHERE "Name" = 'platform/Entity' RETURNING "ID" """,
            env,
        )
    )
    _psql(f"CALL portal.sp_semantic_register_entity({_lit(ns)}, 'thing', 'Thing', '', 's', '1', '', NULL, {class_id})", env)
    entity_id = _psql(f"SELECT id FROM portal.semantic_entity WHERE namespace = {_lit(ns)}", env)
    _psql(
        f"""INSERT INTO portal.semantic_request (request_code, version, namespace, entity_id, target_kind, target_name,
              row_type, params_schema, result_schema, content_hash, required_permission, max_rows)
            VALUES ('{ns}.thing.list', '1', {_lit(ns)}, {entity_id}, 'function', 'x', 'portal.inv_stock_lot_row'::regtype, '{{}}', '{{}}', '',
              {_lit(perm)}, 10)""",
        env,
    )
    return {"ns": ns, "role": role_id, "scope": scope_id, "cls": class_id, "user": user_id}


def test_grant_closes_access_gaps_and_keeps_denies(editor_env: dict[str, str]) -> None:
    env = editor_env
    s = _setup(env)
    ns = s["ns"]
    mine = f"role_name = '{ns}_role'"
    gaps_sql = f"SELECT scope_id FROM portal.fn_semantic_entity_class_read_gaps({_lit(ns)}) WHERE user_id = {s['user']}"
    assert _psql(gaps_sql, env) == str(s["scope"])

    grant_sql = f"""SELECT result FROM "Meta".sp_grant_semantic_entity_class_read({_lit(ns)}) WHERE {mine}"""
    assert _psql(grant_sql, env) == "granted"
    assert _psql(gaps_sql, env) == ""
    assert _psql(f"SELECT count(*) FROM portal.fn_semantic_entity_class_read_gaps({_lit(ns)})", env) == "0"
    assert _psql(grant_sql, env) == "already allowed"

    _psql(
        f"SELECT portal.sp_upsert_class_role_access({s['scope']}, {s['role']}, {s['cls']}, 'read', 'deny')",
        env,
    )
    kept = _psql(grant_sql, env)
    assert kept == "kept deny"
    effect = _psql(
        f"SELECT portal.fn_meta_class_role_effect({s['scope']}, {s['role']}, {s['cls']}, 'read')",
        env,
    )
    assert effect == "deny"


def test_roles_without_the_request_permission_get_nothing(editor_env: dict[str, str]) -> None:
    env = editor_env
    s = _setup(env)
    _psql(
        f"""UPDATE portal.semantic_request SET required_permission = 'nobody.has.this'
            WHERE request_code = '{s['ns']}.thing.list'""",
        env,
    )
    _psql(f"""SELECT count(*) FROM "Meta".sp_grant_semantic_entity_class_read({_lit(s['ns'])})""", env)
    assert _psql(
        f"""SELECT count(*) FROM portal."MetaClassRoleAccess" WHERE "RoleID" = {s['role']} AND "ClassID" = {s['cls']}""",
        env,
    ) == "0"


def test_stock_lot_is_owned_by_platform_lot() -> None:
    from goliath_app.inv.semantic import STOCK_LOT_ENTITY

    assert STOCK_LOT_ENTITY.owner_class_name == "platform/Lot"
    assert STOCK_LOT_ENTITY.meta_class_name is None
    assert STOCK_LOT_ENTITY.storage_relation == "inv.v_stock_lot"
