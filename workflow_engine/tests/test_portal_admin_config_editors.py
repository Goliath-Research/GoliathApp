"""Admin and config editors (portal_session_admin_config_editors_api.sql)."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
NAV_SEED = SQL_PG / "seed_platform_nav_tree.sql"


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


def _lit(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    return "'" + text.replace("'", "''") + "'"


def _make_user(env: dict[str, str], label: str) -> tuple[int, int, int]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@test"
    user_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
                VALUES ('{label}', '{email}', 1) RETURNING "ID" """,
            env,
        )
    )
    org = _psql(f"SELECT * FROM portal.sp_organization_create('{label}Org-{user_id}')", env)
    return user_id, int(org.split("|")[0]), int(org.split("|")[1])


def _author_role(env: dict[str, str], user_id: int, scope_id: int) -> int:
    role_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
                VALUES ('record_editor_{uuid.uuid4().hex[:8]}', false) RETURNING "ID" """,
            env,
        )
    )
    _psql(
        f"""INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
            SELECT {role_id}, p."ID" FROM "RBAC"."Permissions" p
            WHERE p."Name" IN ('platform.model.author', 'meta.schema.read', 'meta.object.read', 'meta.object.write')""",
        env,
    )
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'DIRECT', {scope_id}, true, now() AT TIME ZONE 'utc')""",
        env,
    )
    return role_id


@pytest.fixture(scope="module")
def editor_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    subprocess.run(["psql", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(NAV_SEED)], env=env, check=True)
    return env


@pytest.fixture(scope="module")
def author_token(editor_env: dict[str, str]) -> str:
    from workflow_engine.tests.helpers.portal_session_test_helpers import (
        grant_organization_admin,
        grant_role_nav_tree,
        open_session_token,
    )

    env = editor_env
    psql = lambda sql: _psql(sql, env)  # noqa: E731
    user_id, org_id, scope_id = _make_user(env, "Editor")
    grant_organization_admin(psql, org_id, user_id)
    role_id = _author_role(env, user_id, scope_id)
    grant_role_nav_tree(psql, role_id, scope_id)
    return open_session_token(psql, user_id, scope_id=scope_id, role_id=role_id)


@pytest.fixture(scope="module")
def reader_token(editor_env: dict[str, str]) -> str:
    """Role with every /app nav entitlement but no permissions (no platform.model.author)."""
    from workflow_engine.tests.helpers.portal_session_test_helpers import (
        grant_role_nav_tree,
        open_session_token,
    )

    env = editor_env
    psql = lambda sql: _psql(sql, env)  # noqa: E731
    user_id, _org_id, scope_id = _make_user(env, "Reader")
    role_id = int(
        _psql(
            f"""INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
                VALUES ('nav_reader_{uuid.uuid4().hex[:8]}', false) RETURNING "ID" """,
            env,
        )
    )
    _psql(
        f"""INSERT INTO "RBAC"."UserRoleGrants" ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
            VALUES ({user_id}, {role_id}, 'DIRECT', {scope_id}, true, now() AT TIME ZONE 'utc')""",
        env,
    )
    grant_role_nav_tree(psql, role_id, scope_id)
    return open_session_token(psql, user_id, scope_id=scope_id, role_id=role_id)


def _kind_type(env: dict[str, str], kind: str) -> str:
    name = f"test/{kind}_doc_{uuid.uuid4().hex[:6]}"
    schema = {
        "type": "object",
        "properties": {"enabled": {"type": "boolean"}, "label": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["enabled"],
    }
    _psql(f"INSERT INTO wf.data_type (name, version, kind, schema_json) VALUES ({_lit(name)}, '1', 'object', {_lit(schema)}::jsonb)", env)
    _psql(f"SELECT cfg.sp_register_kind_document_type({_lit(kind)}, {_lit(name)})", env)
    return name


def _unregister(env: dict[str, str], kind: str) -> None:
    _psql(f"DELETE FROM cfg.kind_document_type WHERE kind = {_lit(kind)}", env)


def test_functions_executable_by_portal(editor_env: dict[str, str]) -> None:
    missing = _psql(
        """
        SELECT string_agg(p.oid::regprocedure::text, ', ')
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'portal'
          AND p.proname IN (
            'sp_session_cfg_document_list', 'sp_session_cfg_document_get', 'sp_session_cfg_document_type',
            'sp_session_cfg_document_save', 'sp_session_cfg_document_action',
            'sp_session_org_list', 'sp_session_org_save',
            'fn_published_site_document')
          AND NOT has_function_privilege('goliath_portal', p.oid, 'EXECUTE')
        """,
        editor_env,
    )
    assert missing == ""
    assert _psql(
        "SELECT has_function_privilege('goliath_portal', 'cfg.sp_register_kind_document_type(text,text)', 'EXECUTE')",
        editor_env,
    ) == "f"


def test_unregistered_kind_is_view_only(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    _unregister(env, "site")
    doc = json.loads(_psql(f"SELECT portal.sp_session_cfg_document_type({_lit(author_token)}, 'site')", env))
    assert doc["document_schema"] is None
    with pytest.raises(RuntimeError, match="GS409"):
        _psql(
            f"""SELECT portal.sp_session_cfg_document_save({_lit(author_token)}, 'site', NULL,
                {_lit({"name": "s1", "document": {}})}::jsonb)""",
            env,
        )
    with pytest.raises(RuntimeError, match="GS400"):
        _psql(f"SELECT * FROM portal.sp_session_cfg_document_list({_lit(author_token)}, 'nope')", env)


def test_typed_document_lifecycle(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    _kind_type(env, "pipeline_profile")
    try:
        name = f"prof_{uuid.uuid4().hex[:6]}"
        doc_id = int(
            _psql(
                f"""SELECT portal.sp_session_cfg_document_save({_lit(author_token)}, 'pipeline_profile', NULL,
                    {_lit({"name": name, "document": {"enabled": True, "limit": 3}})}::jsonb)""",
                env,
            )
        )
        with pytest.raises(RuntimeError, match="GS400"):
            _psql(
                f"""SELECT portal.sp_session_cfg_document_save({_lit(author_token)}, 'pipeline_profile', {doc_id},
                    {_lit({"document": {"enabled": True, "other": 1}})}::jsonb)""",
                env,
            )
        with pytest.raises(RuntimeError, match="GS400"):
            _psql(
                f"""SELECT portal.sp_session_cfg_document_save({_lit(author_token)}, 'pipeline_profile', {doc_id},
                    {_lit({"document": {"enabled": "yes"}})}::jsonb)""",
                env,
            )
        with pytest.raises(RuntimeError, match="GS400"):
            _psql(
                f"""SELECT portal.sp_session_cfg_document_save({_lit(author_token)}, 'pipeline_profile', {doc_id},
                    {_lit({"document": {"limit": 1}})}::jsonb)""",
                env,
            )
        same = int(
            _psql(
                f"""SELECT portal.sp_session_cfg_document_save({_lit(author_token)}, 'pipeline_profile', {doc_id},
                    {_lit({"document": {"enabled": False}})}::jsonb)""",
                env,
            )
        )
        assert same == doc_id
        got = json.loads(
            _psql(f"SELECT portal.sp_session_cfg_document_get({_lit(author_token)}, 'pipeline_profile', {doc_id})", env)
        )
        assert got["document"] == {"enabled": False}
        assert got["document_schema"]["required"] == ["enabled"]
        _psql(
            f"SELECT portal.sp_session_cfg_document_action({_lit(author_token)}, 'pipeline_profile', {doc_id}, 'publish')",
            env,
        )
        new_id = int(
            _psql(
                f"""SELECT portal.sp_session_cfg_document_save({_lit(author_token)}, 'pipeline_profile', {doc_id},
                    {_lit({"document": {"enabled": True}})}::jsonb)""",
                env,
            )
        )
        assert new_id != doc_id
        assert _psql(f"SELECT version || '|' || status FROM cfg.pipeline_profile WHERE id = {new_id}", env) == "2|draft"
        assert _psql(f"SELECT status FROM cfg.pipeline_profile WHERE id = {doc_id}", env) == "published"
        _psql(
            f"SELECT portal.sp_session_cfg_document_action({_lit(author_token)}, 'pipeline_profile', {new_id}, 'retire')",
            env,
        )
        with pytest.raises(RuntimeError, match="GS4"):
            _psql(
                f"""SELECT portal.sp_session_cfg_document_save({_lit(author_token)}, 'pipeline_profile', {new_id},
                    {_lit({"document": {"enabled": True}})}::jsonb)""",
                env,
            )
        audited = _psql(
            "SELECT count(*) FROM portal.record_editor_audit WHERE entity = 'cfg_pipeline_profile'", env
        )
        assert int(audited) >= 3
    finally:
        _unregister(env, "pipeline_profile")


def test_cfg_writes_need_model_author(editor_env: dict[str, str], reader_token: str) -> None:
    env = editor_env
    _psql(f"SELECT count(*) FROM portal.sp_session_cfg_document_list({_lit(reader_token)}, 'site')", env)
    with pytest.raises(RuntimeError, match="GS403|denied|author"):
        _psql(
            f"""SELECT portal.sp_session_cfg_document_save({_lit(reader_token)}, 'site', NULL,
                {_lit({"name": "x", "document": {}})}::jsonb)""",
            env,
        )


def test_org_list_and_god_only_save(editor_env: dict[str, str], author_token: str) -> None:
    env = editor_env
    rows = _psql(f"SELECT count(*) FROM portal.sp_session_org_list({_lit(author_token)})", env)
    assert int(rows) >= 1
    with pytest.raises(RuntimeError, match="GS403|god|architect|denied"):
        _psql(
            f"SELECT portal.sp_session_org_save({_lit(author_token)}, NULL, {_lit({'name': 'NewOrgX'})}::jsonb)",
            env,
        )

def test_published_site_document_resolves_by_id_and_default(editor_env: dict[str, str]) -> None:
    """portal.fn_published_site_document returns published documents only."""
    env = editor_env
    suffix = uuid.uuid4().hex[:8]
    other = f"other_{suffix}"
    # Isolated documents; clean up published rows we insert.
    default_id = _psql(
        f"""INSERT INTO cfg.site (name, version, status, content_hash, document_json)
            VALUES ('default', 'test-{suffix}', 'published', 'h1',
                    {_lit({"marker": "default-"+suffix})}::jsonb)
            RETURNING id""",
        env,
    )
    other_id = _psql(
        f"""INSERT INTO cfg.site (name, version, status, content_hash, document_json)
            VALUES ({_lit(other)}, '1', 'published', 'h2',
                    {_lit({"marker": "other-"+suffix})}::jsonb)
            RETURNING id""",
        env,
    )
    draft_id = _psql(
        f"""INSERT INTO cfg.site (name, version, status, content_hash, document_json)
            VALUES ({_lit("draft_"+suffix)}, '1', 'draft', 'h3',
                    {_lit({"marker": "draft-"+suffix})}::jsonb)
            RETURNING id""",
        env,
    )
    try:
        by_default = json.loads(_psql(f"SELECT portal.fn_published_site_document({default_id})", env) or "null")
        assert by_default["marker"] == f"default-{suffix}"
        by_other = json.loads(_psql(f"SELECT portal.fn_published_site_document({other_id})", env) or "null")
        assert by_other["marker"] == f"other-{suffix}"
        # Prefer the published row named 'default' when no id is given. Other
        # published 'default' rows may already exist; the function still returns
        # some published document named default, or the latest published site.
        defaulted = json.loads(_psql("SELECT portal.fn_published_site_document(NULL)", env) or "null")
        assert isinstance(defaulted, dict)
        # A draft must not be resolved by id.
        draft = _psql(f"SELECT portal.fn_published_site_document({draft_id}) IS NULL", env)
        assert draft == "t"
        missing = _psql("SELECT portal.fn_published_site_document(0) IS NULL", env)
        assert missing == "t"
    finally:
        _psql(f"DELETE FROM cfg.site WHERE id IN ({default_id}, {other_id}, {draft_id})", env)


