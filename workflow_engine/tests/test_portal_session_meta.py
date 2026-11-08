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


def _grant_meta_permissions(env: dict[str, str], user_id: int, permissions: tuple[str, ...] = META_PERMISSIONS) -> int:
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
    _psql(
        f"""
        INSERT INTO "RBAC"."UserRoleGrants" (
          "UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc"
        )
        VALUES ({user_id}, {role_id}, 'DIRECT', NULL, true, now() AT TIME ZONE 'utc')
        """,
        env,
    )
    return role_id


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
) -> str:
    opened = portal_client.session_open(user_id, active_scope_id=scope_id)
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
    _grant_meta_permissions(portal_meta_env, user_id, ("meta.schema.read",))
    opened = portal_client.session_open(user_id, active_scope_id=None)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            "SELECT class_name, schema_flattened_json IS NOT NULL FROM portal.sp_session_meta_class_get(%s, %s)",
            (opened.session_token, "portal/NavNode"),
        ).fetchone()
        assert row is not None
        assert row[0] == "portal/NavNode"
        assert row[1] is True

        lineage = conn.execute(
            "SELECT lineage_role, class_name FROM portal.sp_session_meta_class_lineage(%s, %s)",
            (opened.session_token, "portal/NavNode"),
        ).fetchall()
        roles = {str(r[0]) for r in lineage}
        assert "self" in roles

        fields = conn.execute(
            "SELECT field_name, is_local FROM portal.sp_session_meta_class_fields(%s, %s)",
            (opened.session_token, "portal/NavNode"),
        ).fetchall()
        assert isinstance(fields, list)


def test_session_meta_unknown_class_gs404(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaMiss")
    _grant_meta_permissions(portal_meta_env, user_id, ("meta.schema.read",))
    opened = portal_client.session_open(user_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        with pytest.raises(psycopg.Error) as excinfo:
            conn.execute(
                "SELECT class_id FROM portal.sp_session_meta_class_get(%s, %s)",
                (opened.session_token, f"no/such/class_{uuid.uuid4().hex}"),
            )
        assert "GS404" in str(excinfo.value)


def test_session_get_data_type_wrapped(portal_client: PortalClient, portal_meta_env: dict[str, str]) -> None:
    user_id = _create_user(portal_meta_env, "DT")
    _grant_meta_permissions(portal_meta_env, user_id, ("meta.schema.read",))
    opened = portal_client.session_open(user_id)
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        row = conn.execute(
            "SELECT name, schema_json IS NOT NULL FROM portal.sp_session_get_data_type(%s, %s, %s)",
            (opened.session_token, "meta/class/portal/NavNode", None),
        ).fetchone()
        assert row is not None
        assert row[0] == "meta/class/portal/NavNode"
        assert row[1] is True


def test_session_meta_obj_write_requires_scope(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaWriteNoScope")
    _grant_meta_permissions(portal_meta_env, user_id)
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
    _grant_meta_permissions(portal_meta_env, user_id)
    org_row = _psql(f"SELECT * FROM portal.sp_organization_create('MetaOrg-{user_id}')", portal_meta_env)
    scope_id = int(org_row.split("|")[1])
    token = _open_session_scoped(portal_client, user_id, scope_id=scope_id)
    doc = {"Caption": "RoundTripNode", "Seq": 42}
    conninfo = build_portal_conninfo()
    with psycopg.connect(conninfo) as conn:
        insert_row = conn.execute(
            "SELECT portal.sp_session_meta_obj_insert(%s, %s, %s::jsonb)",
            (token, "portal/NavNode", json.dumps(doc)),
        ).fetchone()
        assert insert_row is not None
        obj_id = insert_row[0]
        merge_row = conn.execute(
            "SELECT document FROM portal.sp_session_meta_obj_get(%s, %s)",
            (token, obj_id),
        ).fetchone()
        assert merge_row is not None
        merged = merge_row[0]
        assert merged["Caption"] == "RoundTripNode"
        assert int(merged["Seq"]) == 42


def test_session_meta_obj_rejects_unknown_field(
    portal_client: PortalClient,
    portal_meta_env: dict[str, str],
) -> None:
    user_id = _create_user(portal_meta_env, "MetaBadKey")
    _grant_meta_permissions(portal_meta_env, user_id)
    org_row = _psql(f"SELECT * FROM portal.sp_organization_create('MetaBad-{user_id}')", portal_meta_env)
    scope_id = int(org_row.split("|")[1])
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
