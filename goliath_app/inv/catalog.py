"""Inventory module ActionSpec entries (core level; child apps may override)."""

from __future__ import annotations

from goliath_app.actions.spec import ActionExposure, ActionLevel, ActionSpec
from goliath_app.inv.models import (
    AdjustStockInput,
    AdjustStockOutput,
    IssueStockStubInput,
    IssueStockStubOutput,
    ReceiveStockInput,
    ReceiveStockOutput,
)

ACTION_CATALOG = [
    ActionSpec(
        action_name="inv.stock.receive",
        namespace="inv",
        level=ActionLevel.CORE,
        entity_code="stock_lot",
        display_name="Receive stock",
        description=(
            "Receive a purchase order line into a bin lot. Updates moving average cost "
            "unless the item uses standard costing."
        ),
        exposure=ActionExposure.RBAC,
        required_permission="inv.stock.receive",
        input_model=ReceiveStockInput,
        output_model=ReceiveStockOutput,
        schema_version="1",
        capability="inv.stock",
        tool="inv.stock.receive",
        in_process_handler="goliath_app.inv.handlers:handle_receive_stock",
    ),
    ActionSpec(
        action_name="inv.stock.adjust",
        namespace="inv",
        level=ActionLevel.CORE,
        entity_code="stock_lot",
        display_name="Adjust stock",
        description="Signed quantity adjustment on a stock lot (cycle count variance, shrink, etc.).",
        exposure=ActionExposure.RBAC,
        required_permission="inv.stock.adjust",
        input_model=AdjustStockInput,
        output_model=AdjustStockOutput,
        schema_version="1",
        capability="inv.stock",
        tool="inv.stock.adjust",
        in_process_handler="goliath_app.inv.handlers:handle_adjust_stock",
    ),
    ActionSpec(
        action_name="inv.stock.issue",
        namespace="inv",
        level=ActionLevel.CORE,
        entity_code="stock_lot",
        display_name="Issue stock (stub)",
        description=(
            "Domain-neutral issue that decrements a lot and records an opaque ref. "
            "Child apps extend with traveler/genealogy wiring."
        ),
        exposure=ActionExposure.RBAC,
        required_permission="inv.stock.issue",
        input_model=IssueStockStubInput,
        output_model=IssueStockStubOutput,
        schema_version="1",
        capability="inv.stock",
        tool="inv.stock.issue",
        in_process_handler="goliath_app.inv.handlers:handle_issue_stock_stub",
    ),
]
