"""Electronic signatures (H4): signer, meaning, time and content hash bound to a record."""

from __future__ import annotations

import os
import subprocess
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
PORTAL_TEST_PASSWORD = "signature_test_pw"


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
        env=env, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def _one(conn: psycopg.Connection, sql: LiteralString, params: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return tuple(row)


class Signer:
    def __init__(self, env: dict[str, str], token: str, user_id: int, scope_id: int, session_id: int) -> None:
        self.env = env
        self.token = token
        self.user_id = user_id
        self.scope_id = scope_id
        self.session_id = session_id


def _signer(env: dict[str, str], name: str) -> Signer:
    psql = lambda sql: _psql(sql, env)  # noqa: E731
    user_id = int(psql(
        f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('{name}', 'sig-{uuid.uuid4().hex[:8]}@test', 1) RETURNING "ID" """
    ))
    org = psql(f"SELECT * FROM portal.sp_organization_create('SigOrg-{user_id}')")
    org_id, scope_id = int(org.split("|")[0]), int(org.split("|")[1])
    grant_organization_admin(psql, org_id, user_id)
    role_id = int(psql(
        f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope") VALUES ('sig_{uuid.uuid4().hex[:8]}', false) RETURNING "ID" """
    ))
    for perm in ("meta.schema.read", "meta.object.read", "meta.object.write"):
        psql(
            f"""INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
                SELECT {role_id}, "ID" FROM "RBAC"."Permissions" WHERE "Name" = '{perm}' LIMIT 1"""
        )
    psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'SCOPED', {scope_id}, true, now())"""
    )
    grant_role_nav_tree(psql, role_id, scope_id)
    token = open_session_token(psql, user_id, scope_id=scope_id, role_id=role_id)
    session_id = int(psql(f"""SELECT "ID" FROM "RBAC"."Sessions" WHERE "UserID" = {user_id} ORDER BY "ID" DESC LIMIT 1"""))
    return Signer(env, token, user_id, scope_id, session_id)


@pytest.fixture(scope="module")
def sig_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True, capture_output=True)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)], env=env, check=True, capture_output=True)
    escaped = PORTAL_TEST_PASSWORD.replace("'", "''")
    _psql(f"ALTER ROLE goliath_portal WITH LOGIN PASSWORD '{escaped}'", env)
    os.environ["GOLIATH_PORTAL_PASSWORD"] = PORTAL_TEST_PASSWORD
    # Test meanings; installations create their own through God Architect.
    _psql(
        """
        SELECT "Meta".sp_obj_insert(
          (SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'platform/SignatureMeaning'),
          jsonb_build_object('Label', 'Approved (test)', 'Meaning', 'test.approved'))
        WHERE NOT EXISTS (
          SELECT 1 FROM "Meta"."ObjValues" v
          WHERE v."ClassID" = (SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'platform/SignatureMeaning')
            AND v."Data" ->> 'Meaning' = 'test.approved')
        """,
        env,
    )
    return env


def _record(conn: psycopg.Connection, token: str, label: str) -> int:
    return int(_one(
        conn, "SELECT portal.sp_session_meta_obj_insert(%s, %s, %s::jsonb)",
        (token, "platform/Person", '{"Label": "' + label + '"}'),
    )[0])


def _sign(conn: psycopg.Connection, token: str, kind: str, key: int, meaning: str = "test.approved") -> tuple[Any, ...]:
    return _one(
        conn, "SELECT signature_obj_id, content_sha256 FROM portal.sp_session_sign(%s, %s, %s, %s, %s)",
        (token, kind, str(key), meaning, "Reviewed in test"),
    )


def _statuses(conn: psycopg.Connection, token: str, kind: str, key: int) -> list[str]:
    return [str(r[0]) for r in conn.execute(
        "SELECT status FROM portal.sp_session_signatures(%s, %s, %s)", (token, kind, str(key))
    ).fetchall()]


def test_sign_verify_and_detect_change(sig_env: dict[str, str]) -> None:
    s = _signer(sig_env, "Signer One")
    with psycopg.connect(build_portal_conninfo(), autocommit=True) as conn:
        obj = _record(conn, s.token, "To sign")
        sig_id, sha = _sign(conn, s.token, "meta.object", obj)
        assert len(sha) == 64
        assert _statuses(conn, s.token, "meta.object", obj) == ["valid"]
        row = _one(
            conn, "SELECT signer_full_name, meaning_label, comment FROM portal.sp_session_signatures(%s, 'meta.object', %s)",
            (s.token, str(obj)),
        )
        assert row == ("Signer One", "Approved (test)", "Reviewed in test")

        conn.execute("SELECT portal.sp_session_meta_obj_update(%s, %s, %s::jsonb)", (s.token, obj, '{"Label": "Changed"}'))
        assert _statuses(conn, s.token, "meta.object", obj) == ["content_changed"]

    with psycopg.connect(_conninfo(sig_env), autocommit=True) as owner:
        kinds = [r[0] for r in owner.execute(
            """SELECT "ChangeKind" FROM "Meta"."ObjValuesHistory" WHERE "ObjID" = %s ORDER BY "HistoryID" """, (sig_id,)
        ).fetchall()]
        assert "object.create" in kinds and "values.insert" in kinds


def test_signatures_and_signed_records_are_immutable(sig_env: dict[str, str]) -> None:
    s = _signer(sig_env, "Signer Two")
    with psycopg.connect(build_portal_conninfo(), autocommit=True) as conn:
        obj = _record(conn, s.token, "Immutable")
        sig_id, _ = _sign(conn, s.token, "meta.object", obj)
    with psycopg.connect(_conninfo(sig_env), autocommit=True) as owner:
        with pytest.raises(psycopg.Error, match="cannot be changed"):
            owner.execute("""UPDATE "Meta"."ObjValues" SET "Data" = "Data" || '{"Comment": "x"}' WHERE "ObjID" = %s""", (sig_id,))
        with pytest.raises(psycopg.Error, match="cannot be changed"):
            owner.execute("""DELETE FROM "Meta"."Objs" WHERE "ID" = %s""", (sig_id,))
        with pytest.raises(psycopg.Error, match="electronically signed"):
            owner.execute("""DELETE FROM "Meta"."Objs" WHERE "ID" = %s""", (obj,))


def test_signing_requires_recent_sign_in(sig_env: dict[str, str]) -> None:
    s = _signer(sig_env, "Signer Three")
    _psql(
        f"""UPDATE "RBAC"."Sessions" SET "AuthenticatedAtUtc" = now() - interval '1 hour' WHERE "ID" = {s.session_id}""",
        sig_env,
    )
    with psycopg.connect(build_portal_conninfo(), autocommit=True) as conn:
        obj = _record(conn, s.token, "Stale")
        with pytest.raises(psycopg.Error, match="recent sign-in"):
            _sign(conn, s.token, "meta.object", obj)


def test_unknown_meaning_and_other_tenant_are_refused(sig_env: dict[str, str]) -> None:
    s = _signer(sig_env, "Signer Four")
    other = _signer(sig_env, "Other Tenant")
    with psycopg.connect(build_portal_conninfo(), autocommit=True) as conn:
        obj = _record(conn, s.token, "Tenant record")
        with pytest.raises(psycopg.Error, match="unknown signature meaning"):
            _sign(conn, s.token, "meta.object", obj, meaning="test.nonexistent")
        _sign(conn, s.token, "meta.object", obj)
        with pytest.raises(psycopg.Error):
            _sign(conn, other.token, "meta.object", obj)
        with pytest.raises(psycopg.Error):
            conn.execute("SELECT * FROM portal.sp_session_signatures(%s, 'meta.object', %s)", (other.token, str(obj)))


def test_signed_run_cannot_be_purged(sig_env: dict[str, str]) -> None:
    s = _signer(sig_env, "Run Signer")
    with psycopg.connect(_conninfo(sig_env), autocommit=True) as owner:
        name = f"SignedFlow_{uuid.uuid4().hex[:8]}"
        def_id = int(_one(owner, "INSERT INTO wf.workflow_def (name) VALUES (%s) RETURNING id", (name,))[0])
        version_id = int(_one(owner, "INSERT INTO wf.workflow_version (workflow_def_id) VALUES (%s) RETURNING id", (def_id,))[0])
        inst = int(_one(
            owner,
            "INSERT INTO wf.workflow_instance (workflow_version_id, status, completed_at_utc) "
            "VALUES (%s, 'COMPLETED', now() - interval '30 days') RETURNING id",
            (version_id,),
        )[0])
        owner.execute(
            """SELECT "Meta".sp_obj_insert(
                 (SELECT "ID" FROM "Meta"."Classes" WHERE "Name" = 'platform/RetentionPolicy'),
                 jsonb_build_object('Label', 'Test', 'RecordKind', 'wf.run', 'WorkflowName', %s::text,
                                    'RetentionDays', 0, 'LegalHold', false))""",
            (name,),
        )
    with psycopg.connect(build_portal_conninfo(), autocommit=True) as conn:
        _, sha = _sign(conn, s.token, "wf.instance", inst)
        assert len(sha) == 64
        assert _statuses(conn, s.token, "wf.instance", inst) == ["valid"]
    with psycopg.connect(_conninfo(sig_env), autocommit=True) as owner:
        row = _one(owner, "SELECT purged, reason FROM wf.sp_purge_run_history(ARRAY[%s]::bigint[], 'test')", (inst,))
        assert row == (False, "electronically signed")


def test_signature_internals_are_not_executable_by_portal_role(sig_env: dict[str, str]) -> None:
    with psycopg.connect(_conninfo(sig_env), autocommit=True) as owner:
        rows = owner.execute(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'portal' AND p.proname LIKE 'fn\\_signature\\_%%' "
            "AND has_function_privilege('goliath_portal', p.oid, 'EXECUTE')"
        ).fetchall()
        assert rows == []
