"""Inventory module semantic registry entries."""

from __future__ import annotations

from goliath_app.inv.models import (
    ItemRow,
    ListItemsParams,
    ListPurchaseOrdersParams,
    ListSupplierItemsParams,
    PurchaseOrderRow,
    StockLotRow,
    StockLotsByItemParams,
    SupplierItemRow,
)
from goliath_app.semantic.spec import SemanticAttributeSpec, SemanticEntitySpec, SemanticRequestSpec

ITEM_ENTITY = SemanticEntitySpec(
    namespace="inv",
    code="item",
    display_name="Item",
    description="Domain-neutral item master with on-hand quantity and costing.",
    schema_version="1",
    row_model=ItemRow,
    storage_relation="inv.v_item",
    attributes=(
        SemanticAttributeSpec("item_id", "item_id", "integer", "key", ()),
        SemanticAttributeSpec(
            "organization_id",
            "organization_id",
            "integer",
            "filter",
            ("eq",),
        ),
        SemanticAttributeSpec(
            "item_number",
            "item_number",
            "string",
            "filter",
            ("eq", "starts_with"),
        ),
        SemanticAttributeSpec("active", "active", "boolean", "list", ()),
    ),
)

PURCHASE_ORDER_ENTITY = SemanticEntitySpec(
    namespace="inv",
    code="purchase_order",
    display_name="Purchase order",
    description="Supplier purchase order header.",
    schema_version="1",
    row_model=PurchaseOrderRow,
    storage_relation="inv.v_purchase_order",
    attributes=(
        SemanticAttributeSpec("purchase_order_id", "purchase_order_id", "integer", "key", ()),
        SemanticAttributeSpec(
            "organization_id",
            "organization_id",
            "integer",
            "filter",
            ("eq",),
        ),
        SemanticAttributeSpec(
            "status",
            "status",
            "string",
            "filter",
            ("eq",),
        ),
    ),
)

STOCK_LOT_ENTITY = SemanticEntitySpec(
    namespace="inv",
    code="stock_lot",
    display_name="Stock lot",
    description="On-hand inventory lot in a bin.",
    schema_version="1",
    row_model=StockLotRow,
    storage_relation="inv.v_stock_lot",
    attributes=(
        SemanticAttributeSpec("stock_lot_id", "stock_lot_id", "integer", "key", ()),
        SemanticAttributeSpec(
            "organization_id",
            "organization_id",
            "integer",
            "filter",
            ("eq",),
        ),
        SemanticAttributeSpec("item_id", "item_id", "integer", "filter", ("eq",)),
    ),
)

SUPPLIER_ITEM_ENTITY = SemanticEntitySpec(
    namespace="inv",
    code="supplier_item",
    display_name="Supplier item",
    description="Supplier catalog line linked to an internal item.",
    schema_version="1",
    row_model=SupplierItemRow,
    storage_relation="inv.v_supplier_item",
    attributes=(
        SemanticAttributeSpec("supplier_item_id", "supplier_item_id", "integer", "key", ()),
        SemanticAttributeSpec(
            "organization_id",
            "organization_id",
            "integer",
            "filter",
            ("eq",),
        ),
        SemanticAttributeSpec("item_id", "item_id", "integer", "filter", ("eq",)),
    ),
)

INV_ENTITIES: list[SemanticEntitySpec] = [
    ITEM_ENTITY,
    PURCHASE_ORDER_ENTITY,
    STOCK_LOT_ENTITY,
    SUPPLIER_ITEM_ENTITY,
]

INV_REQUESTS: list[SemanticRequestSpec] = [
    SemanticRequestSpec(
        request_code="inv.item.list",
        version="1",
        namespace="inv",
        entity_code="item",
        target_kind="function",
        target_name="inv.fn_semantic_list_items",
        params_model=ListItemsParams,
        result_row_model=ItemRow,
    ),
    SemanticRequestSpec(
        request_code="inv.purchase_order.list",
        version="1",
        namespace="inv",
        entity_code="purchase_order",
        target_kind="function",
        target_name="inv.fn_semantic_list_purchase_orders",
        params_model=ListPurchaseOrdersParams,
        result_row_model=PurchaseOrderRow,
    ),
    SemanticRequestSpec(
        request_code="inv.stock_lot.by_item",
        version="1",
        namespace="inv",
        entity_code="stock_lot",
        target_kind="function",
        target_name="inv.fn_semantic_stock_lots_by_item",
        params_model=StockLotsByItemParams,
        result_row_model=StockLotRow,
    ),
    SemanticRequestSpec(
        request_code="inv.supplier_item.list",
        version="1",
        namespace="inv",
        entity_code="supplier_item",
        target_kind="function",
        target_name="inv.fn_semantic_list_supplier_items",
        params_model=ListSupplierItemsParams,
        result_row_model=SupplierItemRow,
    ),
]
