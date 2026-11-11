"""Session-bound Meta read/write APIs (portal.sp_session_meta_*)."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest

from goliath_app.portal import PortalClient
from goliath_app.portal.connection import build_portal_conninfo
from workflow_engine.tests.helpers.portal_session_test_helpers import ensure_active_role

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
PORTAL_TEST_PASSWORD = "portal_session_meta_test_pw"

META_PERMISSIONS = (
    "meta.schema.read",
    "meta.object.read",
    "meta.object.write",
)


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    if env.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
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


def _create_org_scope(env: dict[str, str], label: str) -> int:
    org_row = _psql(f"SELECT * FROM portal.sp_organization_create('{label}')", env)
    return int(org_row.split("|")[1])


def _grant_meta_permissions(
    env: dict[str, str],
    user_id: int,
    permissions: tuple[str, ...] = META_PERMISSIONS,
    scope_id: int | None = None,
) -> int:
    role_name = f"meta_test_{uuid.uuid4().hex[:8]}"
    escaped_role = role_name.replace("'", "''")
    role_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
            VALUES ('{escaped_role}', false)
            RETURNING "ID"
            """,
            env,
        )
    )
    for perm in permissions:
        perm_id = _psql(
            f"""SELECT "ID" FROM "RBAC"."Permissions" WHERE "Name" = '{perm.replace("'", "''")}' LIMIT 1""",
            env,
        )
        assert perm_id, f"missing permission seed for {perm}"
        _psql(
            f"""
            INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
            SELECT {role_id}, {perm_id}
            WHERE NOT EXISTS (
              SELECT 1 FROM "RBAC"."Role_Permissions" rp
              WHERE rp."RoleID" = {role_id} AND rp."PermissionID" = {perm_id}
            )
            """,
            env,
        )
    grant_type = "SCOPED" if scope_id is not None else "GLOBAL"
    scope_sql = str(scope_id) if scope_id is not None else "NULL"
    _psql(
        f"""
        INSERT INTO "RBAC"."UserRoleGrants" (
          "UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc"
        )
        VALUES ({user_id}, {role_id}, '{grant_type}', {scope_sql}, true, now() AT TIME ZONE 'utc')
        """,
        env,
    )
    return role_id


def _grant_meta_permissions_scoped(
    env: dict[str, str],
    user_id: int,
    scope_id: int,
    permissions: tuple[str, ...] = META_PERMISSIONS,
) -> int:
    return _grant_meta_permissions(env, user_id, permissions, scope_id=scope_id)


def _expect_meta_object_permission_denied(
    conn: psycopg.Connection,
    token: str,
    obj_id: int,
    *,
    update: bool = False,
) -> str:
    with pytest.raises(psycopg.Error) as excinfo:
        if update:
            conn.execute(
                "SELECT portal.sp_session_meta_obj_update(%s, %s, %s::jsonb)",
                (token, obj_id, json.dumps({"Caption": "X", "Seq": 1})),
            )
        else:
            conn.execute(
                "SELECT document FROM portal.sp_session_meta_obj_get(%s, %s)",
                (token, obj_id),
            )
    text = str(excinfo.value)
    assert "GS403" in text
    assert "meta permission denied" in text.lower()
    conn.rollback()
    return text


def _expect_meta_object_not_found(
    conn: psycopg.Connection,
    token: str,
    obj_id: int,
    *,
    update: bool = False,
) -> str:
    with pytest.raises(psycopg.Error) as excinfo:
        if update:
            conn.execute(
                "SELECT portal.sp_session_meta_obj_update(%s, %s, %s::jsonb)",
                (token, obj_id, json.dumps({"Caption": "X", "Seq": 1})),
            )
        else:
            conn.execute(
                "SELECT document FROM portal.sp_session_meta_obj_get(%s, %s)",
                (token, obj_id),
            )
    text = str(excinfo.value)
    assert "GS404" in text
    assert "meta object not found" in text.lower()
    conn.rollback()
    return text


def _meta_obj_insert(
    conninfo: str,
    token: str,
    document: dict[str, object] | dict[str, int | str],
) -> int:
    with psycopg.connect(conninfo) as conn:
        insert_row = conn.execute(
            "SELECT portal.sp_session_meta_obj_insert(%s, %s, %s::jsonb)",
            (token, "portal/NavNode", json.dumps(document)),
        ).fetchone()
        assert insert_row is not None
        return int(insert_row[0])


def _create_user(env: dict[str, str], label: str) -> int:
    email = f"{label}-{uuid.uuid4().hex[:8]}@test"
    return int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('{label}', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )


def _open_session_scoped(
    portal_client: PortalClient,
    user_id: int,
    scope_id: int | None = None,
    *,
    role_id: int | None = None,
) -> str:
    opened = portal_client.session_open(user_id, active_scope_id=scope_id)
    if scope_id is not None:
        ensure_active_role(opened.session_token, role_id=role_id)
    return opened.session_token


@pytest.fixture(scope="module")
def portal_meta_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    escaped = PORTAL_TEST_PASSWORD.replace("'", "''")
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'", env)
    _psql("SELECT portal.sp_nav_ensure_meta_catalog()", env)
    return env


@pytest.fixture(scope="module")
def portal_client(portal_meta_env: dict[str, str]) -> PortalClient:
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    os.environ.setdefault("PGHOST", portal_meta_env["PGHOST"])
    os.environ.setdefault("PGPORT", portal_meta_env["PGPORT"])
    os.environ.setdefault("PGDATABASE", portal_meta_env["PGDATABASE"])
    return PortalClient(build_portal_conninfo())


def test_session_meta_denied_without_token(portal_meta_env: dict[str, str]) -> None:
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT class_id FROM portal.sp_session_meta_class_get('', 'portal/NavNode')",
            )
        assert "GS401" in str(excinfo.value)


def test_session_meta_gs403_without_permission(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaNoPerm")
    token = _open_session_scoped(portal_client, user_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT class_name FROM portal.sp_session_meta_class_get(%s, %s)",
                (token, "portal/NavNode"),
            )
        assert "GS403" in str(excinfo.value)


def test_session_meta_portal_nav_node_lineage_and_fields(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaReader")
    scope_id = _create_org_scope(portal_meta_env, f"MetaReader-{user_id}")
    role_id = _grant_meta_permissions(
        portal_meta_env, user_id, ("meta.schema.read",), scope_id=scope_id
    )
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id, role_id=role_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            "SELECT class_name, schema_flattened_json IS NOT NULL FROM portal.sp_session_meta_class_get(%s, %s)",
            (token, "portal/NavNode"),
        ).fetchone()
        assert row is not None
        assert row[0] == "portal/NavNode"
        assert row[1] is True

        lineage = conn.execute(
            "SELECT lineage_role, class_name FROM portal.sp_session_meta_class_lineage(%s, %s)",
            (token, "portal/NavNode"),
        ).fetchall()
        roles = {str(r[0]) for r in lineage}
        assert "self" in roles

        fields = conn.execute(
            "SELECT field_name, is_local FROM portal.sp_session_meta_class_fields(%s, %s)",
            (token, "portal/NavNode"),
        ).fetchall()
        assert isinstance(fields, list)


def test_session_meta_unknown_class_gs404(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaMiss")
    scope_id = _create_org_scope(portal_meta_env, f"MetaMiss-{user_id}")
    role_id = _grant_meta_permissions(
        portal_meta_env, user_id, ("meta.schema.read",), scope_id=scope_id
    )
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id, role_id=role_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT class_id FROM portal.sp_session_meta_class_get(%s, %s)",
                (token, f"no/such/class_{uuid.uuid4().hex}"),
            )
        assert "GS404" in str(excinfo.value)


def test_session_get_data_type_wrapped(portal_client: PortalClient, portal_meta_env: dict[str, str]) -> None:
    user_id = _create_user(portal_meta_env, "DT")
    scope_id = _create_org_scope(portal_meta_env, f"DT-{user_id}")
    role_id = _grant_meta_permissions(
        portal_meta_env, user_id, ("meta.schema.read",), scope_id=scope_id
    )
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id, role_id=role_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            "SELECT name, schema_json IS NOT NULL FROM portal.sp_session_get_data_type(%s, %s, %s)",
            (token, "meta/class/portal/NavNode", None),
        ).fetchone()
        assert row is not None
        assert row[0] == "meta/class/portal/NavNode"
        assert row[1] is True


def test_session_meta_obj_write_requires_scope(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaWriteNoScope")
    scope_id = _create_org_scope(portal_meta_env, f"MetaWriteNoScope-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_id)
    token = _open_session_scoped(portal_client, user_id, scope_id=None)
    doc = json.dumps({"Caption": "ScopedWrite", "Seq": 7})
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT portal.sp_session_meta_obj_insert(%s, %s, %s::jsonb)",
                (token, "portal/NavNode", doc),
            )
        assert "GS403" in str(excinfo.value)


def test_session_meta_obj_insert_get_roundtrip(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaRoundtrip")
    scope_id = _create_org_scope(portal_meta_env, f"MetaOrg-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_id)
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id)
    doc = {"Caption": "RoundTripNode", "Seq": 42}
    conninfo = build_portal_conninfo()
    obj_id = _meta_obj_insert(conninfo, token, doc)
    with psycopg.connect(conninfo) as conn:
        merge_row = conn.execute(
            "SELECT document FROM portal.sp_session_meta_obj_get(%s, %s)",
            (token, obj_id),
        ).fetchone()
        assert merge_row is not None
        merged = merge_row[0]
        assert merged["Caption"] == "RoundTripNode"
        assert int(merged["Seq"]) == 42


def test_session_meta_obj_list_returns_scoped_instances(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaList")
    scope_id = _create_org_scope(portal_meta_env, f"MetaList-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_id)
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id)
    doc = {"Caption": "ListedNode", "Seq": 11}
    conninfo = build_portal_conninfo()
    obj_id = _meta_obj_insert(conninfo, token, doc)
    with psycopg.connect(conninfo) as conn:
        rows = conn.execute(
            """
            SELECT obj_id, display_label
            FROM portal.sp_session_meta_obj_list(%s, %s, %s, %s, %s)
            """,
            (token, "portal/NavNode", False, 50, 0),
        ).fetchall()
    ids = [int(row[0]) for row in rows]
    labels = {int(row[0]): str(row[1]) for row in rows}
    assert obj_id in ids
    assert labels[obj_id] == "ListedNode"


def test_session_meta_obj_rejects_unknown_field(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaBadKey")
    scope_id = _create_org_scope(portal_meta_env, f"MetaBad-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_id)
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT portal.sp_session_meta_obj_insert(%s, %s, %s::jsonb)",
                (token, "portal/NavNode", json.dumps({"NotAField": 1})),
            )
        assert "unknown field" in str(excinfo.value).lower()


def test_session_meta_revoked_session_denied(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaRevoke")
    _grant_meta_permissions(portal_meta_env, user_id, ("meta.schema.read",))
    opened = portal_client.session_open(user_id)
    portal_client.session_revoke(opened.session_token)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT class_name FROM portal.sp_session_meta_class_get(%s, %s)",
                (opened.session_token, "portal/NavNode"),
            )
        assert "GS401" in str(excinfo.value)


def test_session_meta_obj_global_grant_does_not_authorize_instances(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaGlobalGrant")
    scope_id = _create_org_scope(portal_meta_env, f"MetaGlobal-{user_id}")
    _grant_meta_permissions(portal_meta_env, user_id, META_PERMISSIONS, scope_id=None)
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT portal.sp_session_meta_obj_insert(%s, %s, %s::jsonb)",
                (token, "portal/NavNode", json.dumps({"Caption": "X", "Seq": 1})),
            )
        assert "GS403" in str(excinfo.value)


def test_session_meta_obj_read_denied_without_active_scope(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaReadNoScope")
    scope_id = _create_org_scope(portal_meta_env, f"MetaReadNs-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_id)
    token_scoped = _open_session_scoped(portal_client, user_id, scope_id=scope_id)
    conninfo = build_portal_conninfo()
    obj_id = _meta_obj_insert(conninfo, token_scoped, {"Caption": "ScopeRead", "Seq": 3})
    token_null_scope = _open_session_scoped(portal_client, user_id, scope_id=None)
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT document FROM portal.sp_session_meta_obj_get(%s, %s)",
                (token_null_scope, obj_id),
            )
        assert "GS403" in str(excinfo.value)


def test_session_meta_obj_cross_scope_read_denied(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaCrossRead")
    scope_a = _create_org_scope(portal_meta_env, f"MetaScopeA-{user_id}")
    scope_b = _create_org_scope(portal_meta_env, f"MetaScopeB-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_a)
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_b)
    token_a = _open_session_scoped(portal_client, user_id, scope_id=scope_a)
    conninfo = build_portal_conninfo()
    obj_id = _meta_obj_insert(conninfo, token_a, {"Caption": "TenantA", "Seq": 9})
    token_b = _open_session_scoped(portal_client, user_id, scope_id=scope_b)
    with psycopg.connect(conninfo) as conn:
        _expect_meta_object_not_found(conn, token_b, obj_id)


def test_session_meta_obj_cross_scope_update_denied(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaCrossUpd")
    scope_a = _create_org_scope(portal_meta_env, f"MetaUpdA-{user_id}")
    scope_b = _create_org_scope(portal_meta_env, f"MetaUpdB-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_a)
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_b)
    token_a = _open_session_scoped(portal_client, user_id, scope_id=scope_a)
    conninfo = build_portal_conninfo()
    obj_id = _meta_obj_insert(conninfo, token_a, {"Caption": "UpdA", "Seq": 4})
    token_b = _open_session_scoped(portal_client, user_id, scope_id=scope_b)
    with psycopg.connect(conninfo) as conn:
        _expect_meta_object_not_found(conn, token_b, obj_id, update=True)


def test_session_meta_obj_writer_without_schema_read_indistinguishable_patch(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaWriterNoSchema")
    scope_a = _create_org_scope(portal_meta_env, f"MetaWnsA-{user_id}")
    scope_b = _create_org_scope(portal_meta_env, f"MetaWnsB-{user_id}")
    admin_id = _create_user(portal_meta_env, "MetaWriterAdmin")
    _grant_meta_permissions_scoped(portal_meta_env, admin_id, scope_a)
    admin_token = _open_session_scoped(portal_client, admin_id, scope_id=scope_a)
    conninfo = build_portal_conninfo()
    in_scope_id = _meta_obj_insert(conninfo, admin_token, {"Caption": "InScope", "Seq": 2})
    _grant_meta_permissions_scoped(
        portal_meta_env,
        user_id,
        scope_b,
        ("meta.object.write",),
    )
    _grant_meta_permissions_scoped(
        portal_meta_env,
        user_id,
        scope_a,
        ("meta.object.write",),
    )
    writer_token = _open_session_scoped(portal_client, user_id, scope_id=scope_a)
    never_allocated_id = int(
        _psql(
            'SELECT COALESCE(MAX(o."ID"), 0) + 50001 FROM "Meta"."Objs" o',
            portal_meta_env,
        )
    )
    catalog_obj_id = int(
        _psql(
            'SELECT o."ID" FROM "Meta"."Objs" o ORDER BY o."ID" LIMIT 1',
            portal_meta_env,
        )
    )
    if _psql(
        f'SELECT COUNT(*) FROM portal."ScopedMetaObjects" WHERE "ObjID" = {catalog_obj_id}',
        portal_meta_env,
    ) != "0":
        pytest.skip("catalog anchor obj is tenanted in this environment")

    errors: list[str] = []
    for obj_id in (in_scope_id, never_allocated_id, catalog_obj_id, in_scope_id + 1):
        with psycopg.connect(conninfo) as conn:
            errors.append(_expect_meta_object_permission_denied(conn, writer_token, obj_id, update=True))

    def _sig(text: str) -> tuple[str, str]:
        assert "GS403" in text
        assert "meta permission denied" in text.lower()
        return ("GS403", "meta permission denied")

    assert {_sig(t) for t in errors} == {("GS403", "meta permission denied")}

    cross_token = _open_session_scoped(portal_client, user_id, scope_id=scope_b)
    with psycopg.connect(conninfo) as conn:
        _expect_meta_object_permission_denied(conn, cross_token, in_scope_id, update=True)


def test_session_meta_obj_not_found_indistinguishable_get_and_update(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaOracle")
    scope_a = _create_org_scope(portal_meta_env, f"MetaOracleA-{user_id}")
    scope_b = _create_org_scope(portal_meta_env, f"MetaOracleB-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_a)
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_b)
    token_b = _open_session_scoped(portal_client, user_id, scope_id=scope_b)
    token_a = _open_session_scoped(portal_client, user_id, scope_id=scope_a)
    conninfo = build_portal_conninfo()
    cross_scope_id = _meta_obj_insert(conninfo, token_a, {"Caption": "Hidden", "Seq": 1})
    never_allocated_id = int(
        _psql(
            'SELECT COALESCE(MAX(o."ID"), 0) + 50000 FROM "Meta"."Objs" o',
            portal_meta_env,
        )
    )
    catalog_obj_id = int(
        _psql(
            'SELECT o."ID" FROM "Meta"."Objs" o ORDER BY o."ID" LIMIT 1',
            portal_meta_env,
        )
    )
    if _psql(
        f'SELECT COUNT(*) FROM portal."ScopedMetaObjects" WHERE "ObjID" = {catalog_obj_id}',
        portal_meta_env,
    ) != "0":
        pytest.skip("catalog anchor obj is tenanted in this environment")

    get_errors: list[str] = []
    for obj_id in (never_allocated_id, catalog_obj_id, cross_scope_id):
        with psycopg.connect(conninfo) as conn:
            get_errors.append(_expect_meta_object_not_found(conn, token_b, obj_id))

    update_errors: list[str] = []
    for obj_id in (never_allocated_id, catalog_obj_id, cross_scope_id):
        with psycopg.connect(conninfo) as conn:
            update_errors.append(_expect_meta_object_not_found(conn, token_b, obj_id, update=True))
    def _normalized_not_found_signature(text: str) -> tuple[str, str]:
        assert "GS404" in text
        assert "meta object not found" in text.lower()
        return ("GS404", "meta object not found")

    get_sigs = {_normalized_not_found_signature(t) for t in get_errors}
    update_sigs = {_normalized_not_found_signature(t) for t in update_errors}
    assert get_sigs == {("GS404", "meta object not found")}
    assert update_sigs == {("GS404", "meta object not found")}


def test_session_meta_obj_strips_forged_tenancy_metadata(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaForgeMeta")
    scope_a = _create_org_scope(portal_meta_env, f"MetaForgeA-{user_id}")
    scope_b = _create_org_scope(portal_meta_env, f"MetaForgeB-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_a)
    token_a = _open_session_scoped(portal_client, user_id, scope_id=scope_a)
    conninfo = build_portal_conninfo()
    obj_id = _meta_obj_insert(
        conninfo,
        token_a,
        {
            "Caption": "Forge",
            "Seq": 5,
            "scope_id": scope_b,
            "OrganizationID": 99999,
        },
    )
    tenancy = _psql(
        f'SELECT "ScopeID" FROM portal."ScopedMetaObjects" WHERE "ObjID" = {obj_id}',
        portal_meta_env,
    )
    assert int(tenancy) == scope_a


def test_session_meta_obj_unscoped_catalog_obj_not_addressable(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaCatalogHole")
    scope_id = _create_org_scope(portal_meta_env, f"MetaCat-{user_id}")
    _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_id)
    catalog_obj_id = int(
        _psql(
            'SELECT o."ID" FROM "Meta"."Objs" o ORDER BY o."ID" LIMIT 1',
            portal_meta_env,
        )
    )
    has_tenancy = _psql(
        f'SELECT COUNT(*) FROM portal."ScopedMetaObjects" WHERE "ObjID" = {catalog_obj_id}',
        portal_meta_env,
    )
    if has_tenancy != "0":
        pytest.skip("catalog anchor obj is tenanted in this environment")
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT document FROM portal.sp_session_meta_obj_get(%s, %s)",
                (token, catalog_obj_id),
            )
        assert "GS404" in str(excinfo.value)


def test_session_meta_obj_permission_revocation_denies_read(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaRevokeObj")
    scope_id = _create_org_scope(portal_meta_env, f"MetaRevObj-{user_id}")
    role_id = _grant_meta_permissions_scoped(portal_meta_env, user_id, scope_id)
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id)
    conninfo = build_portal_conninfo()
    obj_id = _meta_obj_insert(conninfo, token, {"Caption": "RevokeMe", "Seq": 8})
    _psql(
        f'UPDATE "RBAC"."UserRoleGrants" SET "Active" = false '
        f'WHERE "UserID" = {user_id} AND "RoleID" = {role_id}',
        portal_meta_env,
    )
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT document FROM portal.sp_session_meta_obj_get(%s, %s)",
                (token, obj_id),
            )
        assert "GS403" in str(excinfo.value)
