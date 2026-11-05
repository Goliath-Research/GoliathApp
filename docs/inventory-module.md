# Inventory module (`inv`)

GoliathApp ships an **optional**, domain-neutral inventory and purchasing module in the PostgreSQL schema `inv` ([PR #34](https://github.com/Goliath-Research/GoliathApp/pull/34)). Child applications enable and extend it; GoliathApp does not reference factory, crop, or omics concepts.

## What is included

| Area | Tables / APIs |
| --- | --- |
| Item master | `inv.item`, units and conversions |
| Supplier catalog | `inv.supplier`, `inv.supplier_item`, `inv.supplier_item_price_break` |
| ASL | `inv.approved_supplier` |
| Cross-refs | `inv.customer_item_ref`, `inv.item_alternate` |
| Stock | `inv.location`, `inv.bin`, `inv.stock_lot`, `inv.stock_move`, `inv.stock_reservation`, `inv.stock_adjustment` |
| Cycle counts | `inv.cycle_count`, `inv.cycle_count_line` |
| Reorder | `inv.reorder_point` |
| Purchasing | `inv.purchase_order`, `inv.purchase_order_line`, `inv.receipt` |
| Costing | Moving average default (`inv.item.avg_unit_cost`); optional standard cost per item (`costing_method = standard`). **FIFO lot costing is not implemented**; add only when a buyer requires it. |

Semantic namespace **`inv`** registers entities such as `inv.item`, `inv.purchase_order`, `inv.stock_lot`, and `inv.supplier_item` with read requests (`inv.item.list`, etc.) via `portal.sp_run_semantic_request`.

Core write **`ActionSpec`** rows (entry point `goliath.action_catalogs` / `inv`):

| Action | Purpose |
| --- | --- |
| `inv.stock.receive` | PO line receipt into a bin lot; ASL check; moving average update |
| `inv.stock.adjust` | Signed adjustment on a lot |
| `inv.stock.issue` | Stub issue: decrement lot, record opaque `ref_type` / `ref_id` for child genealogy |

Child apps override or wrap these actions (same `action_name` + `overrides`) to attach travelers, QC holds, or crop/omics attributes.

## Enablement

1. Apply GoliathApp schema (`workflow_engine/sql_pg/apply_schema.sh` includes `inv_*.sql`).
2. Seed semantics: `python3 workflow_engine/sql_pg/seed_semantic_catalog.py`.
3. Seed actions: `python3 workflow_engine/sql_pg/seed_action_catalog.py`.
4. Grant RBAC permissions (`inv.stock.*`) to storekeeper roles in the child app.

Factory/Crop/Omics repos register **`mfg.*` / app namespaces** that alias or extend `inv.*` entities; they do not fork the `inv` tables.

## Extension points

- **Meta classes** for extra item attributes (child app apply scripts + `SemanticEntitySpec.meta_class_name`).
- **Action overrides** via `goliath.action_catalogs` entry points (`overrides="inv"`).
- **Issue stub** `ref_type` / `ref_id` — wire to work orders, field applications, or lab consumption in the child app.

## Related docs

- [Semantic extensions](semantic-extensions.md)
- GoliathFactory `docs/plan.md` — Inventory & Purchasing, decision #9 (module location) and #10 (costing default)
