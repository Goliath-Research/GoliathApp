"""Organization administrators must not edit global role permissions.

The product path is the one the security API runs: an organization-admin
session calls portal.sp_session_set_role_permission, which
portalSessionSecurity invokes for action set_role_permission
(apps/platform-host/src/app/api/portal/security/route.ts and
apps/platform-host/src/server/portal/bridge.ts).

These tests fail while that function writes "RBAC"."Role_Permissions" for any
role id. They pass once edits are limited to roles created in the caller's
organization, built-in roles (organization_admin, god_architect) can be changed
only by an active God Architect session, and platform.model.architect cannot be
granted onto a tenant role.

The only session writer of role-permission rows is
portal.sp_session_set_role_permission. portal.sp_set_role_permission is also
used by portal.sp_sync_god_architect_operator_entitlements during schema and
nav seeding; that path is not a caller-supplied role id and is not covered here.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import psycopg
import pytest

from goliath_app.portal.connection import build_portal_conninfo
from workflow_engine.tests.helpers.portal_session_test_helpers import open_session_token

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"

ORG_ADMIN_BASELINE = (
    "meta.schema.read",
    "meta.object.read",
    "meta.object.write",
    "platform.model.author",
    "platform.security.admin",
    "inv.stock.receive",
    "inv.stock.adjust",
    "inv.stock.issue",
    "workflow.validation.plan",
)


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    env.setdefault("PGSSLMODE", "disable")
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


def _role_permissions(psql, role_id: int) -> set[str]:
    raw = psql(
        f"""
        SELECT p."Name"
        FROM "RBAC"."Role_Permissions" rp
        INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
        WHERE rp."RoleID" = {int(role_id)}
        ORDER BY 1
        """
    )
    return {line for line in raw.splitlines() if line}


def _restore_builtin_permissions(psql, admin_role_id: int, god_role_id: int) -> None:
    names = ", ".join("'" + name.replace("'", "''") + "'" for name in ORG_ADMIN_BASELINE)
    psql(
        f"""
        DO $restore$
        DECLARE
          v_name text;
        BEGIN
          FOREACH v_name IN ARRAY ARRAY[{names}]::text[]
          LOOP
            PERFORM portal.sp_set_role_permission({int(admin_role_id)}, v_name, true);
          END LOOP;
          PERFORM portal.sp_set_role_permission({int(admin_role_id)}, 'platform.model.architect', false);
          PERFORM portal.sp_set_role_permission({int(admin_role_id)}, 'semantic.restricted.probe', false);
          PERFORM portal.sp_set_role_permission({int(god_role_id)}, 'platform.model.architect', true);
          PERFORM portal.sp_security_meta_refresh_cache();
        END
        $restore$;
        """
    )


def _register_restricted_probe(psql) -> None:
    psql(
        """
        CALL portal.sp_semantic_register_entity(
          'core',
          'organization',
          'Organization',
          'organization',
          'portal.organization',
          '1',
          'role-perm-escalation',
          NULL,
          NULL
        )
        """
    )
    entity_id = int(
        psql(
            """
            SELECT id FROM portal.semantic_entity
            WHERE namespace = 'core' AND code = 'organization'
            """
        )
    )
    psql(
        f"""
        CALL portal.sp_semantic_register_request(
          'core.restricted_probe',
          '1',
          'core',
          {entity_id},
          'function',
          'portal.fn_semantic_core_list_organizations',
          'portal.core_organization_row',
          '{{}}'::jsonb,
          '{{}}'::jsonb,
          'role-perm-escalation',
          NULL,
          'semantic.restricted.probe',
          50,
          NULL
        )
        """
    )


class World:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.psql = lambda sql: _psql(sql, env)
        self.admin_role_id = int(
            self.psql("""SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin' LIMIT 1""")
        )
        self.god_role_id = int(self.psql("SELECT portal.fn_god_architect_role_id()"))
        suffix = uuid.uuid4().hex[:8]
        self.org_a_admin_id = self._user(f"a1{suffix}@test")
        self.org_a_peer_id = self._user(f"a2{suffix}@test")
        self.org_b_admin_id = self._user(f"b1{suffix}@test")
        self.god_user_id = self._user(f"god{suffix}@test")
        self.org_a_id, self.scope_a = self._org(f"OrgA{suffix}", self.org_a_admin_id)
        self.psql(
            f"SELECT grant_id FROM portal.sp_organization_set_admin({self.org_a_id}, {self.org_a_peer_id})"
        )
        self.org_b_id, self.scope_b = self._org(f"OrgB{suffix}", self.org_b_admin_id)
        subprocess.run(
            ["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)],
            env=env,
            check=True,
        )
        self.psql(
            f"SELECT portal.sp_security_meta_grant_god_architect_to_user({self.god_user_id})"
        )
        _restore_builtin_permissions(self.psql, self.admin_role_id, self.god_role_id)
        _register_restricted_probe(self.psql)
        self.token_a = open_session_token(
            self.psql, self.org_a_admin_id, scope_id=self.scope_a, role_id=self.admin_role_id
        )
        self.token_a_peer = open_session_token(
            self.psql, self.org_a_peer_id, scope_id=self.scope_a, role_id=self.admin_role_id
        )
        self.token_b = open_session_token(
            self.psql, self.org_b_admin_id, scope_id=self.scope_b, role_id=self.admin_role_id
        )
        self.token_god = open_session_token(
            self.psql, self.god_user_id, scope_id=self.scope_a, role_id=self.god_role_id
        )

    def _user(self, email: str) -> int:
        return int(
            self.psql(
                f"""
                INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('Role perm', '{email}', 1)
                RETURNING "ID"
                """
            )
        )

    def _org(self, name: str, user_id: int) -> tuple[int, int]:
        row = self.psql(f"SELECT * FROM portal.sp_organization_create('{name}')")
        org_id, scope_id = (int(part) for part in row.split("|")[:2])
        self.psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {user_id})")
        return org_id, scope_id


@pytest.fixture(scope="module")
def world() -> World:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    portal_password = os.environ.get("GOLIATH_PORTAL_PASSWORD", "").strip()
    if not portal_password:
        pytest.skip("GOLIATH_PORTAL_PASSWORD is not set")
    env = _pg_env()
    for key, value in env.items():
        if key.startswith("PG"):
            os.environ[key] = value
    os.environ["GOLIATH_PORTAL_PASSWORD"] = portal_password
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    escaped = portal_password.replace("'", "''")
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'", env)
    return World(env)


def _portal():
    conn = psycopg.connect(build_portal_conninfo())
    conn.autocommit = True
    return conn


def _attempt(conn, token: str, role_id: int, permission: str, granted: bool):
    try:
        row = conn.execute(
            "SELECT granted FROM portal.sp_session_set_role_permission(%s, %s, %s, %s)",
            (token, role_id, permission, granted),
        ).fetchone()
        return ("ok", None if row is None else row[0])
    except psycopg.Error as exc:
        return ("error", exc.sqlstate, str(exc))


def _session_has(conn, token: str, permission: str) -> bool:
    row = conn.execute(
        """
        SELECT portal.fn_session_has_permission(
          s.session_id, s.user_id, s.active_scope_id, %s
        )
        FROM portal.fn_session_resolve(%s) s
        """,
        (permission, token),
    ).fetchone()
    return bool(row and row[0])


def _semantic_has(conn, user_id: int, permission: str) -> bool:
    row = conn.execute(
        "SELECT portal.fn_semantic_session_has_permission(%s, %s)",
        (user_id, permission),
    ).fetchone()
    return bool(row and row[0])


def _probe(conn, token: str):
    try:
        rows = conn.execute(
            """
            SELECT jsonb_agg(to_jsonb(r))
            FROM portal.sp_run_semantic_request(%s, %s, '1', '{}'::jsonb, NULL) r
            """,
            (token, "core.restricted_probe"),
        ).fetchone()
        return ("ok", rows[0] if rows else None)
    except psycopg.Error as exc:
        return ("error", exc.sqlstate, str(exc))


def _listed_roles(conn, token: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT role_id, name FROM portal.sp_session_list_roles(%s)",
        (token,),
    ).fetchall()
    return {name: int(role_id) for role_id, name in rows}


def _create_role(conn, token: str, name: str) -> int:
    row = conn.execute(
        "SELECT role_id FROM portal.sp_session_create_role(%s, %s)",
        (token, name),
    ).fetchone()
    assert row is not None and row[0]
    return int(row[0])


def _assert_refused(result, action: str) -> None:
    assert result[0] == "error" and result[1] == "GS403", (
        f"{action} must be refused with GS403, got {result!r}"
    )


def test_same_organization_can_edit_role_it_created(world: World) -> None:
    """Tenant-created roles stay editable inside that organization, except architect."""
    with _portal() as conn:
        role_id = _create_role(conn, world.token_a, f"tenant_{uuid.uuid4().hex[:8]}")
        granted = _attempt(conn, world.token_a, role_id, "meta.object.read", True)
        assert granted == ("ok", True), granted
        assert "meta.object.read" in _role_permissions(world.psql, role_id)

        peer = _attempt(conn, world.token_a_peer, role_id, "meta.object.write", True)
        assert peer == ("ok", True), peer
        assert "meta.object.write" in _role_permissions(world.psql, role_id)

        before = _role_permissions(world.psql, role_id)
        architect = _attempt(conn, world.token_a, role_id, "platform.model.architect", True)
        after = _role_permissions(world.psql, role_id)
        _assert_refused(architect, f"grant platform.model.architect on a tenant role; rows={sorted(after)}")
        assert "platform.model.architect" not in after
        assert after == before | {"meta.object.read", "meta.object.write"}


def test_other_organization_cannot_edit_that_role(world: World) -> None:
    with _portal() as conn:
        role_id = _create_role(conn, world.token_a, f"foreign_{uuid.uuid4().hex[:8]}")
        own = _attempt(conn, world.token_a, role_id, "meta.object.read", True)
        assert own == ("ok", True), own

        before = _role_permissions(world.psql, role_id)
        grant = _attempt(conn, world.token_b, role_id, "meta.schema.read", True)
        after_grant = _role_permissions(world.psql, role_id)
        revoke = _attempt(conn, world.token_b, role_id, "meta.object.read", False)
        after_revoke = _role_permissions(world.psql, role_id)
        violations = []
        if grant[0] != "error" or grant[1] != "GS403":
            violations.append(f"grant returned {grant!r}; rows={sorted(after_grant)}")
        if "meta.schema.read" in after_grant:
            violations.append("meta.schema.read was inserted on the other organization's role")
        if revoke[0] != "error" or revoke[1] != "GS403":
            violations.append(f"revoke returned {revoke!r}; rows={sorted(after_revoke)}")
        if "meta.object.read" not in after_revoke:
            violations.append("meta.object.read was deleted from the other organization's role")
        if after_revoke != before:
            violations.append(f"permissions changed from {sorted(before)} to {sorted(after_revoke)}")
        assert not violations, "\n".join(violations)


def test_org_admin_cannot_edit_builtin_global_role_permissions(world: World) -> None:
    """Shared organization_admin and god_architect rows must not move."""
    _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)
    try:
        with _portal() as conn:
            listed = _listed_roles(conn, world.token_a)
            assert listed.get("organization_admin") == world.admin_role_id
            assert listed.get("god_architect") == world.god_role_id
            catalog = {
                name
                for (name,) in conn.execute(
                    "SELECT name FROM portal.sp_session_list_permissions(%s, NULL)",
                    (world.token_a,),
                ).fetchall()
            }
            assert "platform.model.architect" in catalog
            assert "semantic.restricted.probe" in catalog
            assert "platform.security.admin" in catalog

            # The caller's own role edit still works, so a later refusal is about the
            # target role rather than a missing security-admin or nav grant.
            scratch = _create_role(conn, world.token_a, f"scratch_{uuid.uuid4().hex[:8]}")
            scratch_grant = _attempt(conn, world.token_a, scratch, "meta.object.read", True)
            assert scratch_grant == ("ok", True), scratch_grant

            admin_before = _role_permissions(world.psql, world.admin_role_id)
            god_before = _role_permissions(world.psql, world.god_role_id)
            assert "platform.model.architect" not in admin_before
            assert "semantic.restricted.probe" not in admin_before
            assert "meta.object.write" in admin_before
            assert "platform.security.admin" in admin_before
            assert "platform.model.architect" in god_before
            assert _session_has(conn, world.token_b, "meta.object.write")
            assert _session_has(conn, world.token_b, "platform.security.admin")
            assert not _session_has(conn, world.token_b, "platform.model.architect")
            assert not _semantic_has(conn, world.org_b_admin_id, "semantic.restricted.probe")
            probe_before = _probe(conn, world.token_b)
            assert probe_before[0] == "error" and probe_before[1] == "GS403", probe_before
            god_ok = conn.execute(
                "SELECT role_id FROM portal.fn_session_assert_god_architect(%s)",
                (world.token_god,),
            ).fetchone()
            assert god_ok is not None and int(god_ok[0]) == world.god_role_id

            # Mechanism check: a committed role-permission row changes every tenant
            # that uses the role, and removing architect fails the God Architect gate.
            world.psql(
                f"""
                SELECT portal.sp_set_role_permission({world.admin_role_id}, 'semantic.restricted.probe', true)
                """
            )
            assert _semantic_has(conn, world.org_a_admin_id, "semantic.restricted.probe")
            assert _semantic_has(conn, world.org_b_admin_id, "semantic.restricted.probe")
            opened = _probe(conn, world.token_b)
            assert opened[0] == "ok", opened
            world.psql(
                f"""
                SELECT portal.sp_set_role_permission({world.admin_role_id}, 'semantic.restricted.probe', false)
                """
            )
            world.psql("SELECT portal.sp_security_meta_refresh_cache()")
            closed = _probe(conn, world.token_b)
            assert closed[0] == "error" and closed[1] == "GS403", closed

            world.psql(
                f"""
                SELECT portal.sp_set_role_permission({world.god_role_id}, 'platform.model.architect', false)
                """
            )
            world.psql("SELECT portal.sp_security_meta_refresh_cache()")
            with pytest.raises(psycopg.Error) as god_denied:
                conn.execute(
                    "SELECT role_id FROM portal.fn_session_assert_god_architect(%s)",
                    (world.token_god,),
                )
            assert god_denied.value.sqlstate == "GS403"
            _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)
            restored = conn.execute(
                "SELECT role_id FROM portal.fn_session_assert_god_architect(%s)",
                (world.token_god,),
            ).fetchone()
            assert restored is not None

            admin_id = listed["organization_admin"]
            god_id = listed["god_architect"]
            violations: list[str] = []

            def record(label: str, result, unchanged: bool) -> None:
                if result[0] != "error" or result[1] != "GS403":
                    violations.append(f"{label}: call returned {result!r}")
                if not unchanged:
                    violations.append(f"{label}: role-permission rows changed")

            result = _attempt(conn, world.token_a, admin_id, "platform.model.architect", True)
            record(
                "grant architect on organization_admin",
                result,
                "platform.model.architect" not in _role_permissions(world.psql, world.admin_role_id),
            )
            if _session_has(conn, world.token_b, "platform.model.architect"):
                violations.append("organization B admin gained platform.model.architect")
            _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)

            result = _attempt(conn, world.token_a, admin_id, "semantic.restricted.probe", True)
            record(
                "grant restricted probe on organization_admin",
                result,
                "semantic.restricted.probe" not in _role_permissions(world.psql, world.admin_role_id),
            )
            if _semantic_has(conn, world.org_b_admin_id, "semantic.restricted.probe"):
                violations.append("organization B admin gained semantic.restricted.probe")
            probe_after = _probe(conn, world.token_b)
            if probe_after[0] != "error" or probe_after[1] != "GS403":
                violations.append(f"restricted probe ran for organization B: {probe_after!r}")
            _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)

            result = _attempt(conn, world.token_a, admin_id, "meta.object.write", False)
            record(
                "revoke meta.object.write from organization_admin",
                result,
                "meta.object.write" in _role_permissions(world.psql, world.admin_role_id),
            )
            if not _session_has(conn, world.token_b, "meta.object.write"):
                violations.append("organization B admin lost meta.object.write")
            _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)

            result = _attempt(conn, world.token_a, admin_id, "platform.security.admin", False)
            record(
                "revoke platform.security.admin",
                result,
                "platform.security.admin" in _role_permissions(world.psql, world.admin_role_id),
            )
            if not _session_has(conn, world.token_b, "platform.security.admin"):
                violations.append("organization B admin lost platform.security.admin")
            _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)

            result = _attempt(conn, world.token_a, god_id, "platform.model.architect", False)
            record(
                "revoke architect from god_architect",
                result,
                "platform.model.architect" in _role_permissions(world.psql, world.god_role_id),
            )
            try:
                still_god = conn.execute(
                    "SELECT role_id FROM portal.fn_session_assert_god_architect(%s)",
                    (world.token_god,),
                ).fetchone()
            except psycopg.Error as exc:
                violations.append(
                    f"God Architect check failed after organization admin edit: {exc.sqlstate} {exc}"
                )
            else:
                if still_god is None or int(still_god[0]) != world.god_role_id:
                    violations.append("God Architect check did not return the god_architect role")
            _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)

            again = _attempt(conn, world.token_a, scratch, "meta.schema.read", True)
            assert again == ("ok", True), again
            assert not violations, "organization admin changed global role permissions:\n" + "\n".join(
                violations
            )
    finally:
        _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)


def test_god_architect_can_edit_builtin_role_permissions(world: World) -> None:
    _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)
    try:
        with _portal() as conn:
            removed = _attempt(
                conn, world.token_god, world.admin_role_id, "inv.stock.issue", False
            )
            assert removed == ("ok", False), removed
            assert "inv.stock.issue" not in _role_permissions(world.psql, world.admin_role_id)
            assert not _session_has(conn, world.token_b, "inv.stock.issue")
            restored = _attempt(
                conn, world.token_god, world.admin_role_id, "inv.stock.issue", True
            )
            assert restored == ("ok", True), restored
            assert "inv.stock.issue" in _role_permissions(world.psql, world.admin_role_id)
            assert "platform.model.architect" in _role_permissions(world.psql, world.god_role_id)
    finally:
        _restore_builtin_permissions(world.psql, world.admin_role_id, world.god_role_id)
