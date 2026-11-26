"""Inventory semantic reads must be denied without an inventory permission.

The portal host forwards a signed-in session to the database with no request allow-list:

    SELECT * FROM portal.sp_run_semantic_request($1, $2, $3, $4::jsonb, NULL::jsonb)

(apps/platform-host/src/server/portal/bridge.ts, portalSessionRunSemanticRequest).
These tests call that function as the goliath_portal login. They fail while a member
whose selected role has no inventory permission can still read the rows.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
SEED_SEMANTIC = SQL_PG / "seed_semantic_catalog.py"

# Local test-database login set by this module. Not a product credential.
PORTAL_PASSWORD = "placeholder-not-a-secret"

INVENTORY_REQUESTS = (
    "inv.item.list",
    "inv.purchase_order.list",
    "inv.stock_lot.by_item",
    "inv.supplier_item.list",
)

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _admin_conninfo() -> str:
    host = os.environ.get("PGHOST", os.environ.get("POSTGRES_HOST", "127.0.0.1"))
    port = os.environ.get("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    db = os.environ.get("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    user = os.environ.get("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    password = os.environ.get("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath_ci"))
    return f"host={host} port={port} dbname={db} user={user} password={password} sslmode=disable"


def _portal_conninfo() -> str:
    host = os.environ.get("PGHOST", os.environ.get("POSTGRES_HOST", "127.0.0.1"))
    port = os.environ.get("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    db = os.environ.get("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    return (
        f"host={host} port={port} dbname={db} user=goliath_portal "
        f"password={PORTAL_PASSWORD} sslmode=disable"
    )


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", "127.0.0.1")
    env.setdefault("PGPORT", "5432")
    env.setdefault("PGUSER", "postgres")
    env.setdefault("PGDATABASE", "goliathapp_schema_test")
    env.setdefault("PGPASSWORD", "goliath_ci")
    env["PGSSLMODE"] = "disable"
    return env


class Db:
    def __init__(self, conninfo: str) -> None:
        self.conninfo = conninfo

    def rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        with psycopg.connect(self.conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else []

    def one(self, sql: str, params: tuple = ()):
        found = self.rows(sql, params)
        assert found, sql
        return found[0][0]


@pytest.fixture(scope="module")
def database() -> dict[str, Db]:
    from shutil import which

    if which("psql") is None:
        pytest.skip("psql not installed")
    env = _pg_env()
    admin = Db(_admin_conninfo())
    try:
        admin.one("SELECT 1")
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL not reachable: {exc.sqlstate}")
    subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    subprocess.run(["python3", str(SEED_SEMANTIC)], env=env, check=True)
    with psycopg.connect(admin.conninfo) as conn:
        conn.execute(
            sql.SQL("ALTER ROLE goliath_portal WITH LOGIN PASSWORD {}").format(sql.Literal(PORTAL_PASSWORD))
        )
    portal = Db(_portal_conninfo())
    portal.one("SELECT 1")
    return {"admin": admin, "portal": portal}


def _create_user(admin: Db, prefix: str) -> int:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@t.test"
    return int(
        admin.one(
            """
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES (%s, %s, 1)
            RETURNING "ID"
            """,
            (prefix, email),
        )
    )


def _create_org(admin: Db, name: str) -> tuple[int, int]:
    row = admin.rows("SELECT organization_id, scope_id FROM portal.sp_organization_create(%s)", (name,))
    return int(row[0][0]), int(row[0][1])


def _add_member(admin: Db, org_id: int, user_id: int) -> None:
    admin.rows("SELECT inserted FROM portal.sp_organization_add_member(%s, %s)", (org_id, user_id))


def _ensure_permission(admin: Db, name: str) -> int:
    found = admin.rows('SELECT "ID" FROM "RBAC"."Permissions" WHERE "Name" = %s ORDER BY "ID" LIMIT 1', (name,))
    if found:
        return int(found[0][0])
    anchor = admin.rows(
        """
        SELECT "ObjID", "OperationID" FROM "RBAC"."Permissions"
        WHERE "Name" = 'meta.object.read'
        ORDER BY "ID" LIMIT 1
        """
    )
    assert anchor, "meta.object.read permission is missing; schema seed did not run"
    return int(
        admin.one(
            """
            INSERT INTO "RBAC"."Permissions" ("Name", "ObjID", "OperationID")
            VALUES (%s, %s, %s)
            RETURNING "ID"
            """,
            (name, anchor[0][0], anchor[0][1]),
        )
    )


def _create_role(admin: Db, permissions: list[str]) -> int:
    role_id = int(
        admin.one(
            """
            INSERT INTO "RBAC"."Roles" ("Name", "BypassScope")
            VALUES (%s, false)
            RETURNING "ID"
            """,
            (f"role-{uuid.uuid4().hex[:12]}",),
        )
    )
    for name in permissions:
        perm_id = _ensure_permission(admin, name)
        admin.rows(
            """
            INSERT INTO "RBAC"."Role_Permissions" ("RoleID", "PermissionID")
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (role_id, perm_id),
        )
    return role_id


def _grant_role(admin: Db, user_id: int, role_id: int, scope_id: int) -> None:
    admin.rows(
        """
        INSERT INTO "RBAC"."UserRoleGrants"
          ("UserID", "RoleID", "GrantType", "ScopeID", "Active", "GrantedAtUtc")
        VALUES (%s, %s, 'SCOPED', %s, true, now())
        """,
        (user_id, role_id, scope_id),
    )


def _request_permissions(admin: Db) -> list[str]:
    names: list[str] = []
    for code in INVENTORY_REQUESTS:
        value = admin.rows(
            """
            SELECT required_permission FROM portal.semantic_request
            WHERE request_code = %s AND version = '1'
            """,
            (code,),
        )
        assert value, code
        if value[0][0]:
            names.append(str(value[0][0]))
    return names


def _open_session(admin: Db, user_id: int, scope_id: int, role_id: int) -> str:
    token = str(
        admin.one(
            "SELECT session_token FROM portal.sp_session_open(%s, %s)",
            (user_id, scope_id),
        )
    )
    admin.rows("SELECT role_id FROM portal.sp_session_set_active_role(%s, %s)", (token, role_id))
    return token


def _plant(admin: Db, org_id: int, suffix: str) -> dict[str, object]:
    item_id = int(
        admin.one(
            """
            INSERT INTO inv.item (
              organization_id, item_number, description, base_unit, avg_unit_cost
            )
            VALUES (%s, %s, 'secret item', 'ea', 17.5)
            RETURNING item_id
            """,
            (org_id, f"ITEM-{suffix}"),
        )
    )
    supplier_id = int(
        admin.one(
            """
            INSERT INTO inv.supplier (organization_id, supplier_code, name)
            VALUES (%s, %s, %s)
            RETURNING supplier_id
            """,
            (org_id, f"SUP-{suffix}", f"Supplier {suffix}"),
        )
    )
    admin.rows(
        """
        INSERT INTO inv.supplier_item (
          organization_id, supplier_id, item_id, supplier_part_number
        )
        VALUES (%s, %s, %s, %s)
        """,
        (org_id, supplier_id, item_id, f"PART-{suffix}"),
    )
    location_id = int(
        admin.one(
            """
            INSERT INTO inv.location (organization_id, location_code, name)
            VALUES (%s, %s, 'store')
            RETURNING location_id
            """,
            (org_id, f"LOC-{suffix}"),
        )
    )
    bin_id = int(
        admin.one(
            "INSERT INTO inv.bin (location_id, bin_code) VALUES (%s, 'A1') RETURNING bin_id",
            (location_id,),
        )
    )
    admin.rows(
        """
        INSERT INTO inv.stock_lot (
          organization_id, item_id, bin_id, lot_number, qty_on_hand, unit_cost
        )
        VALUES (%s, %s, %s, %s, 4, 9.25)
        """,
        (org_id, item_id, bin_id, f"LOT-{suffix}"),
    )
    admin.rows(
        """
        INSERT INTO inv.purchase_order (organization_id, supplier_id, po_number, status)
        VALUES (%s, %s, %s, 'submitted')
        """,
        (org_id, supplier_id, f"PO-{suffix}"),
    )
    return {"item_id": item_id, "marker": suffix}


def _params(org_id: int, item_id: int, request_code: str) -> dict[str, int]:
    if request_code == "inv.stock_lot.by_item":
        return {"organization_id": org_id, "item_id": item_id}
    return {"organization_id": org_id}


def _run(portal: Db, token: str, request_code: str, params: dict[str, int]) -> list[dict]:
    raw = portal.rows(
        """
        SELECT * FROM portal.sp_run_semantic_request(%s, %s, '1', %s::jsonb, NULL::jsonb)
        """,
        (token, request_code, json.dumps(params)),
    )
    rows: list[dict] = []
    for (value,) in raw:
        if isinstance(value, str):
            value = json.loads(value)
        assert isinstance(value, dict)
        rows.append(value)
    return rows


def _inv_counts(admin: Db) -> dict[str, int]:
    names = admin.rows(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'inv' AND c.relkind = 'r'
        ORDER BY c.relname
        """
    )
    counts: dict[str, int] = {}
    for (name,) in names:
        assert _IDENT.match(name)
        counts[name] = int(admin.one(f"SELECT count(*) FROM inv.{name}"))
    return counts


def _permission_label(admin: Db, request_code: str) -> str:
    value = admin.rows(
        """
        SELECT required_permission FROM portal.semantic_request
        WHERE request_code = %s AND version = '1'
        """,
        (request_code,),
    )
    return repr(value[0][0]) if value else "missing"


def _assert_no_inventory_nav(admin: Db, role_id: int) -> None:
    nav = int(
        admin.one(
            """
            SELECT count(*)
            FROM portal."Role2Node" rn
            JOIN portal."NavTree" n ON n."ID" = rn."NodeId"
            WHERE rn."RoleId" = %s AND n."NodePath" LIKE %s
            """,
            (role_id, "/app/inv%"),
        )
    )
    assert nav == 0
    names = [
        str(row[0])
        for row in admin.rows(
            """
            SELECT p."Name"
            FROM "RBAC"."Role_Permissions" rp
            JOIN "RBAC"."Permissions" p ON p."ID" = rp."PermissionID"
            WHERE rp."RoleID" = %s
            """,
            (role_id,),
        )
    ]
    inventory = [name for name in names if name.startswith("inv.") or name.startswith("platform.nav.inv")]
    assert inventory == []


def _assert_denied(admin: Db, portal: Db, token: str, request_code: str, params: dict[str, int], marker: str) -> None:
    before = _inv_counts(admin)
    try:
        rows = _run(portal, token, request_code, params)
    except psycopg.Error as exc:
        primary = ""
        if exc.diag is not None and exc.diag.message_primary:
            primary = exc.diag.message_primary
        blob = f"{exc.sqlstate or ''} {primary}"
        assert exc.sqlstate == "GS403", blob
        assert marker not in blob
        assert _inv_counts(admin) == before
        return
    payload = json.dumps(rows)
    pytest.fail(
        f"{request_code} required_permission={_permission_label(admin, request_code)} "
        f"returned inventory rows containing {marker!r}: {payload}"
    )


def _assert_contains(rows: list[dict], marker: str, fields: tuple[str, ...]) -> None:
    payload = json.dumps(rows)
    assert marker in payload, payload
    for field in fields:
        assert any(field in row for row in rows), payload


@pytest.fixture
def member(database: dict[str, Db]) -> dict[str, object]:
    admin = database["admin"]
    suffix = uuid.uuid4().hex[:8]
    user_id = _create_user(admin, "mem")
    org_id, scope_id = _create_org(admin, f"Org-{suffix}")
    _add_member(admin, org_id, user_id)
    planted = _plant(admin, org_id, suffix)
    role_id = _create_role(admin, ["portal.other_area.use"])
    _grant_role(admin, user_id, role_id, scope_id)
    _assert_no_inventory_nav(admin, role_id)
    token = _open_session(admin, user_id, scope_id, role_id)
    return {
        "admin": admin,
        "portal": database["portal"],
        "token": token,
        "org_id": org_id,
        "item_id": planted["item_id"],
        "marker": suffix,
        "role_id": role_id,
    }


@pytest.mark.parametrize("request_code", INVENTORY_REQUESTS)
def test_member_without_inventory_permission_cannot_read(member: dict[str, object], request_code: str) -> None:
    admin = member["admin"]
    assert isinstance(admin, Db)
    portal = member["portal"]
    assert isinstance(portal, Db)
    _assert_denied(
        admin,
        portal,
        str(member["token"]),
        request_code,
        _params(int(member["org_id"]), int(member["item_id"]), request_code),
        str(member["marker"]),
    )


@pytest.mark.parametrize("request_code", INVENTORY_REQUESTS)
def test_meta_reader_without_inventory_permission_cannot_read(
    database: dict[str, Db], request_code: str
) -> None:
    """platform/Lot class read is not an inventory grant.

    inv.stock_lot is owned by platform/Lot, and meta.object.read satisfies that class
    check. A role with only that permission still must not receive inventory rows.
    """
    admin = database["admin"]
    suffix = uuid.uuid4().hex[:8]
    user_id = _create_user(admin, "meta")
    org_id, scope_id = _create_org(admin, f"MetaOrg-{suffix}")
    _add_member(admin, org_id, user_id)
    planted = _plant(admin, org_id, suffix)
    role_id = _create_role(admin, ["meta.object.read", "portal.other_area.use"])
    _grant_role(admin, user_id, role_id, scope_id)
    _assert_no_inventory_nav(admin, role_id)
    token = _open_session(admin, user_id, scope_id, role_id)
    if request_code == "inv.stock_lot.by_item":
        allowed = admin.one(
            """
            SELECT portal.fn_meta_effective_class_action(
              s.user_id, s.active_scope_id, c."ID", 'read', s.session_id
            )
            FROM portal.fn_session_resolve(%s) s
            JOIN "Meta"."Classes" c ON c."Name" = 'platform/Lot'
            """,
            (token,),
        )
        assert allowed is True
    _assert_denied(
        admin,
        database["portal"],
        token,
        request_code,
        _params(org_id, int(planted["item_id"]), request_code),
        suffix,
    )


@pytest.mark.parametrize("request_code", INVENTORY_REQUESTS)
def test_inventory_read_is_limited_to_the_authorized_organization(
    database: dict[str, Db], request_code: str
) -> None:
    """A role that can read organization A must not read organization B.

    The session scope is A. The request params name B. Membership of B alone must
    not return B's quantities, costs, purchase orders, or suppliers.
    """
    admin = database["admin"]
    portal = database["portal"]
    suffix_a = uuid.uuid4().hex[:8]
    suffix_b = uuid.uuid4().hex[:8]
    user_id = _create_user(admin, "bound")
    org_a, scope_a = _create_org(admin, f"OrgA-{suffix_a}")
    org_b, _scope_b = _create_org(admin, f"OrgB-{suffix_b}")
    _add_member(admin, org_a, user_id)
    _add_member(admin, org_b, user_id)
    planted_a = _plant(admin, org_a, suffix_a)
    planted_b = _plant(admin, org_b, suffix_b)
    role_id = _create_role(admin, ["meta.object.read", "portal.other_area.use", *_request_permissions(admin)])
    _grant_role(admin, user_id, role_id, scope_a)
    token = _open_session(admin, user_id, scope_a, role_id)

    own = _run(portal, token, request_code, _params(org_a, int(planted_a["item_id"]), request_code))
    _assert_contains(own, suffix_a, _expected_fields(request_code))
    _assert_denied(
        admin,
        portal,
        token,
        request_code,
        _params(org_b, int(planted_b["item_id"]), request_code),
        suffix_b,
    )


def test_non_member_cannot_read_inventory(database: dict[str, Db]) -> None:
    admin = database["admin"]
    suffix = uuid.uuid4().hex[:8]
    outsider = _create_user(admin, "out")
    org_id, _scope = _create_org(admin, f"Closed-{suffix}")
    planted = _plant(admin, org_id, suffix)
    home_id, home_scope = _create_org(admin, f"Home-{suffix}")
    _add_member(admin, home_id, outsider)
    role_id = _create_role(admin, ["portal.other_area.use", "meta.object.read"])
    _grant_role(admin, outsider, role_id, home_scope)
    token = _open_session(admin, outsider, home_scope, role_id)
    for code in INVENTORY_REQUESTS:
        _assert_denied(
            admin,
            database["portal"],
            token,
            code,
            _params(org_id, int(planted["item_id"]), code),
            suffix,
        )


def test_portal_login_cannot_read_inv_tables_directly(database: dict[str, Db]) -> None:
    portal = database["portal"]
    with pytest.raises(psycopg.Error) as raised:
        portal.rows("SELECT item_number, avg_unit_cost FROM inv.item")
    assert raised.value.sqlstate == "42501"


def _expected_fields(request_code: str) -> tuple[str, ...]:
    if request_code == "inv.item.list":
        return ("qty_on_hand", "avg_unit_cost")
    if request_code == "inv.purchase_order.list":
        return ("po_number", "supplier_name")
    if request_code == "inv.stock_lot.by_item":
        return ("qty_on_hand", "unit_cost", "lot_number")
    if request_code == "inv.supplier_item.list":
        return ("supplier_code", "supplier_part_number")
    raise AssertionError(request_code)
