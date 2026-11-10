"""Portal session fixtures: org admin grant, scope, and active role selection."""

from __future__ import annotations

from typing import Callable

import psycopg

from goliath_app.portal.connection import build_portal_conninfo


def ensure_active_role(session_token: str, *, role_id: int | None = None) -> None:
    with psycopg.connect(build_portal_conninfo()) as conn:
        if role_id is None:
            conn.execute(
                "SELECT role_id FROM portal.sp_session_auto_select_active_role(%s)",
                (session_token,),
            )
        else:
            conn.execute(
                "SELECT role_id FROM portal.sp_session_set_active_role(%s, %s)",
                (session_token, role_id),
            )


def grant_role_nav_tree(psql: Callable[[str], str], role_id: int, scope_id: int) -> None:
    psql(
        f"""
        DO $grant$
        DECLARE
          v_node int;
        BEGIN
          FOR v_node IN
            SELECT n."ID" FROM portal."NavTree" n WHERE n."NodePath" LIKE '/app%'
          LOOP
            PERFORM portal.sp_grant_role_nav_node({role_id}, v_node, {scope_id});
          END LOOP;
        END $grant$;
        """
    )


def grant_organization_admin_nav_tree(psql: Callable[[str], str], scope_id: int) -> None:
    grant_role_nav_tree(psql, organization_admin_role_id(psql), scope_id)


def grant_organization_admin(psql: Callable[[str], str], org_id: int, user_id: int) -> int:
    row = psql(f"SELECT grant_id FROM portal.sp_organization_set_admin({org_id}, {user_id})")
    scope_id = int(
        psql(
            f"""
            SELECT s."ScopeID"
            FROM "RBAC"."Scopes" s
            WHERE s."OrganizationID" = {org_id} AND s."ScopeType" = 'organization'
            LIMIT 1
            """
        )
    )
    grant_organization_admin_nav_tree(psql, scope_id)
    return int(row)


def organization_admin_role_id(psql: Callable[[str], str]) -> int:
    return int(
        psql("""SELECT "ID" FROM "RBAC"."Roles" WHERE "Name" = 'organization_admin' LIMIT 1""")
    )


def open_session_token(
    psql: Callable[[str], str],
    user_id: int,
    *,
    scope_id: int | None = None,
    role_id: int | None = None,
) -> str:
    if scope_id is None:
        row = psql(f"SELECT session_token FROM portal.sp_session_open({user_id})")
    else:
        row = psql(f"SELECT session_token FROM portal.sp_session_open({user_id}, {scope_id})")
    token = row.split("|")[0]
    if scope_id is not None:
        if role_id is None:
            psql(f"SELECT role_id FROM portal.sp_session_auto_select_active_role('{token}')")
        else:
            psql(f"SELECT role_id FROM portal.sp_session_set_active_role('{token}', {role_id})")
    return token


def grant_platform_security_admin(psql: Callable[[str], str], user_id: int, scope_id: int) -> int:
    """Grant a role that carries platform.security.admin in the given scope."""
    role_id = int(
        psql(
            """
            SELECT r."ID"
            FROM "RBAC"."Roles" r
            INNER JOIN "RBAC"."Role_Permissions" rp ON rp."RoleID" = r."ID"
            INNER JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
            WHERE p."Name" = 'platform.security.admin'
            ORDER BY r."ID"
            LIMIT 1
            """
        )
    )
    psql(
        f"""
        INSERT INTO "RBAC"."UserRoleGrants"
          ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
        SELECT {user_id}, {role_id}, 'SCOPED', {scope_id}, true, now() AT TIME ZONE 'utc'
        WHERE NOT EXISTS (
          SELECT 1 FROM "RBAC"."UserRoleGrants" g
          WHERE g."UserID" = {user_id}
            AND g."RoleID" = {role_id}
            AND g."ScopeID" = {scope_id}
            AND g."Active"
        )
        """
    )
    return role_id


def create_org_with_admin(
    psql: Callable[[str], str],
    user_id: int,
    name: str,
) -> tuple[int, int]:
    escaped = name.replace("'", "''")
    row = psql(f"SELECT * FROM portal.sp_organization_create('{escaped}')")
    org_id, scope_id = int(row.split("|")[0]), int(row.split("|")[1])
    grant_organization_admin(psql, org_id, user_id)
    return org_id, scope_id
