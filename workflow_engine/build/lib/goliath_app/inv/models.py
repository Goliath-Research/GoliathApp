"""Inventory module action and semantic models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from goliath_app.actions.base_models import ActionOutputBase

PositiveQty = Annotated[Decimal, Field(gt=Decimal("0"))]
NonNegativeCost = Annotated[Decimal, Field(ge=Decimal("0"))]


class ItemRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: int
    organization_id: int
    item_number: str
    description: str
    base_unit: str
    costing_method: str
    qty_on_hand: float
    avg_unit_cost: float
    active: bool


class PurchaseOrderRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    purchase_order_id: int
    organization_id: int
    po_number: str
    supplier_code: str
    supplier_name: str
    status: str
    ordered_at_utc: Optional[datetime] = None


class StockLotRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    stock_lot_id: int
    organization_id: int
    item_id: int
    item_number: str
    location_code: str
    bin_code: str
    lot_number: Optional[str] = None
    qty_on_hand: float
    unit_cost: float


class SupplierItemRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    supplier_item_id: int
    organization_id: int
    item_id: int
    item_number: str
    supplier_code: str
    supplier_part_number: str
    preferred: bool
    lead_time_days: Optional[int] = None
    active: bool


class OrgScopedListParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: int
    limit: Optional[PositiveInt] = Field(default=None, le=500)


class ListItemsParams(OrgScopedListParams):
    active: Optional[bool] = None


class ListPurchaseOrdersParams(OrgScopedListParams):
    status: Optional[str] = None


class StockLotsByItemParams(OrgScopedListParams):
    item_id: int


class ListSupplierItemsParams(OrgScopedListParams):
    item_id: Optional[int] = None


class ReceiveStockInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    organization_id: int
    user_id: int
    po_line_id: int
    bin_id: int
    qty: PositiveQty
    lot_number: Optional[str] = None
    unit_price_override: NonNegativeCost | None = None


class ReceiveStockOutput(ActionOutputBase):
    receipt_id: int
    stock_lot_id: int
    avg_unit_cost: float


class AdjustStockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: int
    user_id: int
    stock_lot_id: int
    qty_delta: Decimal
    reason_code: str


class AdjustStockOutput(ActionOutputBase):
    adjustment_id: int
    qty_on_hand: float


class IssueStockStubInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: int
    user_id: int
    stock_lot_id: int
    qty: PositiveQty
    ref_type: str
    ref_id: str


class IssueStockStubOutput(ActionOutputBase):
    stock_move_id: int
    qty_on_hand: float
