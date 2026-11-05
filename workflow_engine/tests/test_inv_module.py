"""Integration tests for the inv inventory module."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

SQL_PG = Path(__file__).resolve().parents[1] / "sql_pg"
APPLY_SH = SQL_PG / "apply_schema.sh"
SEED_SEMANTIC = SQL_PG / "seed_semantic_catalog.py"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGHOST", os.environ.get("POSTGRES_HOST", "localhost"))
    env.setdefault("PGPORT", os.environ.get("POSTGRES_PORT", "5432"))
    env.setdefault("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
    env.setdefault("PGDATABASE", os.environ.get("POSTGRES_DB", "goliathapp_schema_test"))
    if env.get("POSTGRES_PASSWORD"):
        env["PGPASSWORD"] = env["POSTGRES_PASSWORD"]
    env.setdefault("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", "goliath"))
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


@pytest.fixture(scope="module")
def inv_env() -> dict[str, str]:
    from shutil import which

    if not which("psql"):
        pytest.skip("psql not installed")
    env = _pg_env()
    try:
        _psql("SELECT 1", env)
    except RuntimeError:
        pytest.skip("PostgreSQL not reachable")
    for _ in range(2):
        subprocess.run(["bash", str(APPLY_SH)], env=env, check=True)
    subprocess.run(["python3", str(SEED_SEMANTIC)], env=env, check=True)
    return env


def _create_user(env: dict[str, str]) -> int:
    email = f"inv-{uuid.uuid4().hex[:8]}@test"
    return int(
        _psql(
            f"""
            INSERT INTO "RBAC"."Users" ("FullName", email, "Active")
            VALUES ('Inv User', '{email}', 1)
            RETURNING "ID"
            """,
            env,
        )
    )


def _create_org(env: dict[str, str], user_id: int, name: str) -> int:
    escaped = name.replace("'", "''")
    row = _psql(
        f"SELECT * FROM portal.sp_organization_create('{escaped}')",
        env,
    )
    org_id = int(row.split("|")[0])
    _psql(
        f"SELECT inserted FROM portal.sp_organization_add_member({org_id}, {user_id})",
        env,
    )
    return org_id


def _seed_inv_fixture(env: dict[str, str], org_id: int) -> dict[str, int]:
    item_id = int(
        _psql(
            f"""
            INSERT INTO inv.item (organization_id, item_number, description, base_unit)
            VALUES ({org_id}, 'WIDGET-1', 'Test widget', 'ea')
            RETURNING item_id
            """,
            env,
        )
    )
    supplier_id = int(
        _psql(
            f"""
            INSERT INTO inv.supplier (organization_id, supplier_code, name)
            VALUES ({org_id}, 'ACME', 'Acme Supply')
            RETURNING supplier_id
            """,
            env,
        )
    )
    _psql(
        f"""
        INSERT INTO inv.approved_supplier (organization_id, supplier_id, item_id)
        VALUES ({org_id}, {supplier_id}, {item_id})
        """,
        env,
    )
    supplier_item_id = int(
        _psql(
            f"""
            INSERT INTO inv.supplier_item (
              organization_id, supplier_id, item_id, supplier_part_number
            )
            VALUES ({org_id}, {supplier_id}, {item_id}, 'ACME-W1')
            RETURNING supplier_item_id
            """,
            env,
        )
    )
    location_id = int(
        _psql(
            f"""
            INSERT INTO inv.location (organization_id, location_code, name)
            VALUES ({org_id}, 'MAIN', 'Main store')
            RETURNING location_id
            """,
            env,
        )
    )
    bin_id = int(
        _psql(
            f"""
            INSERT INTO inv.bin (location_id, bin_code)
            VALUES ({location_id}, 'A1')
            RETURNING bin_id
            """,
            env,
        )
    )
    po_id = int(
        _psql(
            f"""
            INSERT INTO inv.purchase_order (organization_id, supplier_id, po_number, status)
            VALUES ({org_id}, {supplier_id}, 'PO-1001', 'submitted')
            RETURNING purchase_order_id
            """,
            env,
        )
    )
    po_line_id = int(
        _psql(
            f"""
            INSERT INTO inv.purchase_order_line (
              purchase_order_id, line_number, item_id, supplier_item_id,
              qty_ordered, unit_price
            )
            VALUES ({po_id}, 1, {item_id}, {supplier_item_id}, 10, 2.50)
            RETURNING po_line_id
            """,
            env,
        )
    )
    return {
        "item_id": item_id,
        "bin_id": bin_id,
        "po_line_id": po_line_id,
    }


def test_receive_adjust_issue_and_semantic_reads(inv_env: dict[str, str]) -> None:
    user_id = _create_user(inv_env)
    org_id = _create_org(inv_env, user_id, f"InvOrg-{user_id}")
    fx = _seed_inv_fixture(inv_env, org_id)

    row = _psql(
        f"""
        SELECT receipt_id, stock_lot_id, avg_unit_cost
        FROM inv.sp_stock_receive(
          {org_id}, {user_id}, {fx['po_line_id']}, {fx['bin_id']}, 4, 'LOT-A', NULL
        )
        """,
        inv_env,
    )
    receipt_id, stock_lot_id, avg_cost = row.split("|")
    assert int(receipt_id) > 0
    assert int(stock_lot_id) > 0
    assert Decimal(avg_cost) == Decimal("2.50")

    row2 = _psql(
        f"""
        SELECT receipt_id, stock_lot_id, avg_unit_cost
        FROM inv.sp_stock_receive(
          {org_id}, {user_id}, {fx['po_line_id']}, {fx['bin_id']}, 6, 'LOT-B', NULL
        )
        """,
        inv_env,
    )
    _, _, avg_cost2 = row2.split("|")
    assert Decimal(avg_cost2) == Decimal("2.50")

    adj = _psql(
        f"""
        SELECT adjustment_id, qty_on_hand
        FROM inv.sp_stock_adjust({org_id}, {user_id}, {stock_lot_id}, -1, 'cycle_count')
        """,
        inv_env,
    )
    _, qty_after_adj = adj.split("|")
    assert Decimal(qty_after_adj) == Decimal("3")

    issue = _psql(
        f"""
        SELECT stock_move_id, qty_on_hand
        FROM inv.sp_stock_issue_stub(
          {org_id}, {user_id}, {stock_lot_id}, 2, 'work_order', 'WO-42'
        )
        """,
        inv_env,
    )
    move_id, qty_after_issue = issue.split("|")
    assert int(move_id) > 0
    assert Decimal(qty_after_issue) == Decimal("1")

    token = _psql(
        f"SELECT session_token FROM portal.sp_session_open({user_id})",
        inv_env,
    ).split("|")[0]
    params = json.dumps({"organization_id": org_id})
    items = _psql(
        "SELECT count(*) FROM portal.sp_run_semantic_request("
        f"'{token}', 'inv.item.list', '1', '{params}'::jsonb)",
        inv_env,
    )
    assert int(items) >= 1

    params_lot = json.dumps({"organization_id": org_id, "item_id": fx["item_id"]})
    lots = _psql(
        "SELECT count(*) FROM portal.sp_run_semantic_request("
        f"'{token}', 'inv.stock_lot.by_item', '1', '{params_lot}'::jsonb)",
        inv_env,
    )
    assert int(lots) >= 2


def test_asl_blocks_unapproved_supplier(inv_env: dict[str, str]) -> None:
    user_id = _create_user(inv_env)
    org_id = _create_org(inv_env, user_id, f"InvOrgB-{user_id}")
    fx = _seed_inv_fixture(inv_env, org_id)
    other_supplier = int(
        _psql(
            f"""
            INSERT INTO inv.supplier (organization_id, supplier_code, name)
            VALUES ({org_id}, 'OTHER', 'Other Supply')
            RETURNING supplier_id
            """,
            inv_env,
        )
    )
    po_id = int(
        _psql(
            f"""
            INSERT INTO inv.purchase_order (organization_id, supplier_id, po_number, status)
            VALUES ({org_id}, {other_supplier}, 'PO-BAD', 'submitted')
            RETURNING purchase_order_id
            """,
            inv_env,
        )
    )
    po_line_id = int(
        _psql(
            f"""
            INSERT INTO inv.purchase_order_line (
              purchase_order_id, line_number, item_id, qty_ordered, unit_price
            )
            VALUES ({po_id}, 1, {fx['item_id']}, 1, 1)
            RETURNING po_line_id
            """,
            inv_env,
        )
    )
    with pytest.raises(RuntimeError, match="approved supplier"):
        _psql(
            f"""
            SELECT * FROM inv.sp_stock_receive(
              {org_id}, {user_id}, {po_line_id}, {fx['bin_id']}, 1, NULL, NULL
            )
            """,
            inv_env,
        )


def test_inv_action_catalog_registered() -> None:
    from goliath_app.actions.registry import find_action, reload_action_catalog

    reload_action_catalog()
    receive = find_action("inv.stock.receive")
    assert receive is not None
    assert receive.namespace == "inv"
    assert receive.level.value == "core"
