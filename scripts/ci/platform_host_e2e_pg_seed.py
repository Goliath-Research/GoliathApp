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
    for perm in ("meta.schema.read", "meta.object.read", "meta.object.write"):
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
    scope_a = int(org_a.split("|")[1])
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
