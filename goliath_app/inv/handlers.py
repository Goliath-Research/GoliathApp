"""Inventory module in-process action handlers (call inv.* stored procedures)."""

from __future__ import annotations

from goliath_app.inv.db import db_cursor
from goliath_app.inv.models import (
    AdjustStockInput,
    AdjustStockOutput,
    IssueStockStubInput,
    IssueStockStubOutput,
    ReceiveStockInput,
    ReceiveStockOutput,
)


def handle_receive_stock(inp: ReceiveStockInput) -> ReceiveStockOutput:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT receipt_id, stock_lot_id, avg_unit_cost
            FROM inv.sp_stock_receive(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                inp.organization_id,
                inp.user_id,
                inp.po_line_id,
                inp.bin_id,
                inp.qty,
                inp.lot_number,
                inp.unit_price_override,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return ReceiveStockOutput(
            receipt_id=row[0],
            stock_lot_id=row[1],
            avg_unit_cost=row[2],
        )


def handle_adjust_stock(inp: AdjustStockInput) -> AdjustStockOutput:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT adjustment_id, qty_on_hand
            FROM inv.sp_stock_adjust(%s, %s, %s, %s, %s)
            """,
            (
                inp.organization_id,
                inp.user_id,
                inp.stock_lot_id,
                inp.qty_delta,
                inp.reason_code,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return AdjustStockOutput(adjustment_id=row[0], qty_on_hand=row[1])


def handle_issue_stock_stub(inp: IssueStockStubInput) -> IssueStockStubOutput:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT stock_move_id, qty_on_hand
            FROM inv.sp_stock_issue_stub(%s, %s, %s, %s, %s, %s)
            """,
            (
                inp.organization_id,
                inp.user_id,
                inp.stock_lot_id,
                inp.qty,
                inp.ref_type,
                inp.ref_id,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return IssueStockStubOutput(stock_move_id=row[0], qty_on_hand=row[1])
