#!/usr/bin/env python3
"""Seed disposable PostgreSQL for platform-host authenticated Playwright (CI only)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APPLY_SH = REPO / "workflow_engine" / "sql_pg" / "apply_schema.sh"
NAV_SEED = REPO / "workflow_engine" / "sql_pg" / "seed_platform_nav_tree.sql"
PORTAL_TEST_PASSWORD = "platform_host_e2e_pw"
DEV_SECRET = os.environ.get("GOLIATH_PLATFORM_HOST_DEV_LOGIN_SECRET", "ci-e2e-dev-secret")


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", "localhost")
    env.setdefault("PGPORT", "5432")
    env.setdefault("PGUSER", "postgres")
    env.setdefault("PGDATABASE", "goliathapp_schema_test")
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


def _ensure_e2e_nested_hierarchy(env: dict[str, str]) -> None:
    """CI-only Meta hierarchy + wf.data_type fixtures for hierarchy-driven nested grids."""
    payload_schema = (
        '{"type":"object","properties":{"label":{"type":"string"},"qty":{"type":"integer"}},'
        '"required":["label"],"additionalProperties":false}'
    )
    payload_type_id = _psql(
        f"""
        INSERT INTO wf.data_type (name, version, kind, schema_json)
        VALUES ('e2e/NestedPayload', '1', 'object', '{payload_schema}'::jsonb)
        ON CONFLICT (name, version) DO UPDATE SET schema_json = EXCLUDED.schema_json
        RETURNING id
        """,
        env,
    )
    array_schema = '{"type":"array","items":{"$ref":"goliath:meta/class/e2e/NestedChild"}}'
    child_rows_type_id = _psql(
        f"""
        INSERT INTO wf.data_type (name, version, kind, schema_json)
        VALUES ('e2e/NestedChildRows', '1', 'array', '{array_schema}'::jsonb)
        ON CONFLICT (name, version) DO UPDATE SET schema_json = EXCLUDED.schema_json
        RETURNING id
        """,
        env,
    )
    string_type_id = _psql(
        """SELECT id FROM wf.data_type WHERE name = 'portal/nav/Caption' AND version = '1.0' LIMIT 1""",
        env,
    )
    int_type_id = _psql(
        """SELECT id FROM wf.data_type WHERE name = 'portal/nav/Seq' AND version = '1.0' LIMIT 1""",
        env,
    )
    if not string_type_id or not int_type_id:
        raise RuntimeError("wf.data_type primitives missing for e2e nested hierarchy")

    parent_id = _psql(
        """SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'e2e/NestedParent' LIMIT 1""",
        env,
    )
    if not parent_id:
        parent_id = _psql(
            """INSERT INTO "Meta"."Classes" ("Name") VALUES ('e2e/NestedParent') RETURNING "ID" """,
            env,
        )
    _psql(
        f"""
        INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
        VALUES ({parent_id}, 'ParentLabel', {string_type_id}, true)
        ON CONFLICT ("ClassID", "Name") DO NOTHING
        """,
        env,
    )

    child_id = _psql(
        """SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'e2e/NestedChild' LIMIT 1""",
        env,
    )
    if not child_id:
        child_id = _psql(
            f"""INSERT INTO "Meta"."Classes" ("Name", "ParentID") VALUES ('e2e/NestedChild', {parent_id}) RETURNING "ID" """,
            env,
        )
    _psql(
        f"""
        INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
        VALUES ({child_id}, 'ChildCode', {string_type_id}, true)
        ON CONFLICT ("ClassID", "Name") DO NOTHING
        """,
        env,
    )
    _psql(
        f"""
        INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
        VALUES ({child_id}, 'DetailPayload', {payload_type_id}, false)
        ON CONFLICT ("ClassID", "Name") DO NOTHING
        """,
        env,
    )

    carrier_id = _psql(
        """SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'e2e/NestedCarrier' LIMIT 1""",
        env,
    )
    if not carrier_id:
        carrier_id = _psql(
            """INSERT INTO "Meta"."Classes" ("Name") VALUES ('e2e/NestedCarrier') RETURNING "ID" """,
            env,
        )
    for field_name, type_id, required in (
        ("Caption", string_type_id, True),
        ("Seq", int_type_id, True),
        ("Payload", payload_type_id, True),
    ):
        _psql(
            f"""
            INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
            VALUES ({carrier_id}, '{field_name}', {type_id}, {'true' if required else 'false'})
            ON CONFLICT ("ClassID", "Name") DO NOTHING
            """,
            env,
        )
    _psql("SELECT portal.sp_nav_ensure_meta_catalog()", env)
    child_catalog_type_id = _psql(
        """SELECT id FROM wf.data_type WHERE name = 'meta/class/e2e/NestedChild' ORDER BY id DESC LIMIT 1""",
        env,
    )
    if not child_catalog_type_id:
        raise RuntimeError("meta/class/e2e/NestedChild catalog type missing after sp_nav_ensure_meta_catalog")
    for field_name, type_id, required in (
        ("ChildDoc", child_catalog_type_id, False),
        ("ChildRows", child_rows_type_id, False),
    ):
        _psql(
            f"""
            INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required")
            VALUES ({carrier_id}, '{field_name}', {type_id}, {'true' if required else 'false'})
            ON CONFLICT ("ClassID", "Name") DO NOTHING
            """,
            env,
        )
    _psql("SELECT portal.sp_nav_ensure_meta_catalog()", env)


def _grant_scoped(env: dict[str, str], user_id: int, scope_id: int) -> None:
    role_name = f"e2e_meta_{uuid.uuid4().hex[:8]}"
    role_id = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
            VALUES ('{role_name}', false)
            RETURNING "ID"
            """,
            env,
        )
    )
    for perm in ("meta.schema.read", "meta.object.read", "meta.object.write", "platform.model.author"):
        perm_id = _psql(
            f"""SELECT "ID" FROM "RBAC"."Permissions" WHERE "Name" = '{perm}' LIMIT 1""",
            env,
        )
        _psql(
            f"""
            INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
            SELECT {role_id}, {perm_id}
            WHERE NOT EXISTS (
              SELECT 1 FROM "RBAC"."Role_Permissions"
              WHERE "RoleID" = {role_id} AND "PermissionID" = {perm_id}
            )
            """,
            env,
        )
    _psql(
        f"""
        INSERT INTO "RBAC"."UserRoleGrants" (
          "UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc"
        )
        VALUES ({user_id}, {role_id}, 'DIRECT', {scope_id}, true, now() AT TIME ZONE 'utc')
        """,
        env,
    )


def main() -> int:
    env = _env()
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    escaped = PORTAL_TEST_PASSWORD.replace("'", "''")
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'", env)
    _psql("SELECT portal.sp_nav_ensure_meta_catalog()", env)
    _ensure_e2e_nested_hierarchy(env)

    email_a = f"e2e-primary-{uuid.uuid4().hex[:8]}@test"
    user_a = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('E2E Primary', '{email_a}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )
    org_a = _psql(f"SELECT * FROM portal.sp_organization_create('E2EOrgA')", env)
    org_a_id = int(org_a.split("|")[0])
    scope_a = int(org_a.split("|")[1])
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)], env=env, check=True)
    _psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_a_id}, {user_a})", env)
    _grant_scoped(env, user_a, scope_a)

    email_b = f"e2e-denied-{uuid.uuid4().hex[:8]}@test"
    user_b = int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('E2E Denied', '{email_b}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )
    org_b = _psql(f"SELECT * FROM portal.sp_organization_create('E2EOrgB')", env)
    scope_b = int(org_b.split("|")[1])
    _grant_scoped(env, user_a, scope_b)

    out_dir = REPO / "apps" / "platform-host" / ".e2e"
    out_dir.mkdir(parents=True, exist_ok=True)
    env_file = out_dir / "ci.env"
    env_file.write_text(
        "\n".join(
            [
                f"GOLIATH_P1_DEV_LOGIN_USER_ID={user_a}",
                f"GOLIATH_E2E_SCOPE_ID={scope_a}",
                f"GOLIATH_E2E_DENIED_USER_ID={user_b}",
                f"GOLIATH_E2E_SCOPE_B_ID={scope_b}",
                f"GOLIATH_E2E_DENIED_SCOPE_ID={scope_b}",
                f"GOLIATH_PLATFORM_HOST_DEV_LOGIN=1",
                f"GOLIATH_PLATFORM_HOST_E2E_INTEGRATION=1",
                f"PGSSLMODE=disable",
                f"GOLIATH_PLATFORM_HOST_DEV_LOGIN_SECRET={DEV_SECRET}",
                f"GOLIATH_PORTAL_PASSWORD={PORTAL_TEST_PASSWORD}",
                f"PGHOST={env['PGHOST']}",
                f"PGPORT={env.get('PGPORT', '5432')}",
                f"PGDATABASE={env['PGDATABASE']}",
                f"PGUSER={env.get('PGUSER', 'postgres')}",
                f"PGPASSWORD={env['PGPASSWORD']}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {env_file}")
    print(f"E2E_PRIMARY_USER_ID={user_a}")
    print(f"E2E_SCOPE_ID={scope_a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
