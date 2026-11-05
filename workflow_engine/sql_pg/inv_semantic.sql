-- Semantic namespace, views, and read functions for the inv module.

INSERT INTO portal.semantic_namespace (code, display_name, owner_app)
VALUES ('inv', 'Inventory & purchasing', 'goliath_app')
ON CONFLICT (code) DO UPDATE
  SET display_name = EXCLUDED.display_name,
      owner_app = EXCLUDED.owner_app;

CREATE OR REPLACE VIEW inv.v_item AS
SELECT
  i.item_id,
  i.organization_id,
  i.item_number,
  i.description,
  i.base_unit,
  i.costing_method,
  i.avg_unit_cost,
  i.standard_unit_cost,
  inv.fn_item_qty_on_hand(i.item_id) AS qty_on_hand,
  i.active
FROM inv.item i;

CREATE OR REPLACE VIEW inv.v_purchase_order AS
SELECT
  po.purchase_order_id,
  po.organization_id,
  po.po_number,
  s.supplier_code,
  s.name AS supplier_name,
  po.status,
  po.ordered_at_utc,
  po.created_at_utc
FROM inv.purchase_order po
INNER JOIN inv.supplier s ON s.supplier_id = po.supplier_id;

CREATE OR REPLACE VIEW inv.v_stock_lot AS
SELECT
  sl.stock_lot_id,
  sl.organization_id,
  sl.item_id,
  i.item_number,
  l.location_code,
  b.bin_code,
  sl.lot_number,
  sl.qty_on_hand,
  sl.unit_cost,
  sl.received_at_utc
FROM inv.stock_lot sl
INNER JOIN inv.item i ON i.item_id = sl.item_id
INNER JOIN inv.bin b ON b.bin_id = sl.bin_id
INNER JOIN inv.location l ON l.location_id = b.location_id;

CREATE OR REPLACE VIEW inv.v_supplier_item AS
SELECT
  si.supplier_item_id,
  si.organization_id,
  si.item_id,
  i.item_number,
  s.supplier_code,
  si.supplier_part_number,
  si.preferred,
  si.lead_time_days,
  si.active
FROM inv.supplier_item si
INNER JOIN inv.item i ON i.item_id = si.item_id
INNER JOIN inv.supplier s ON s.supplier_id = si.supplier_id;

CREATE OR REPLACE FUNCTION inv.fn_semantic_assert_org_access(
  p_user_id integer,
  p_organization_id integer
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = inv, portal, pg_temp
AS $$
BEGIN
  IF p_organization_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'organization_id is required');
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM portal."OrganizationMembers" m
    WHERE m."UserID" = p_user_id
      AND m."OrganizationID" = p_organization_id
  ) THEN
    PERFORM portal.fn_semantic_raise('GS403', 'organization scope denied');
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION inv.fn_semantic_list_items(
  p_user_id integer,
  p_params jsonb,
  p_limit integer
)
RETURNS SETOF portal.inv_item_row
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = inv, portal, pg_temp
AS $$
DECLARE
  v_org_id integer;
BEGIN
  v_org_id := (p_params->>'organization_id')::integer;
  PERFORM inv.fn_semantic_assert_org_access(p_user_id, v_org_id);

  RETURN QUERY
  SELECT
    v.item_id,
    v.organization_id,
    v.item_number,
    v.description,
    v.base_unit,
    v.costing_method,
    v.qty_on_hand,
    v.avg_unit_cost,
    v.active
  FROM inv.v_item v
  WHERE v.organization_id = v_org_id
    AND (
      NOT (p_params ? 'active')
      OR v.active = (p_params->>'active')::boolean
    )
  ORDER BY v.item_number
  LIMIT GREATEST(0, COALESCE(p_limit, 500));
END;
$$;

CREATE OR REPLACE FUNCTION inv.fn_semantic_list_purchase_orders(
  p_user_id integer,
  p_params jsonb,
  p_limit integer
)
RETURNS SETOF portal.inv_purchase_order_row
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = inv, portal, pg_temp
AS $$
DECLARE
  v_org_id integer;
BEGIN
  v_org_id := (p_params->>'organization_id')::integer;
  PERFORM inv.fn_semantic_assert_org_access(p_user_id, v_org_id);

  RETURN QUERY
  SELECT
    v.purchase_order_id,
    v.organization_id,
    v.po_number,
    v.supplier_code,
    v.supplier_name,
    v.status,
    v.ordered_at_utc
  FROM inv.v_purchase_order v
  WHERE v.organization_id = v_org_id
    AND (
      NOT (p_params ? 'status')
      OR v.status = p_params->>'status'
    )
  ORDER BY v.created_at_utc DESC
  LIMIT GREATEST(0, COALESCE(p_limit, 500));
END;
$$;

CREATE OR REPLACE FUNCTION inv.fn_semantic_stock_lots_by_item(
  p_user_id integer,
  p_params jsonb,
  p_limit integer
)
RETURNS SETOF portal.inv_stock_lot_row
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = inv, portal, pg_temp
AS $$
DECLARE
  v_org_id integer;
  v_item_id integer;
BEGIN
  v_org_id := (p_params->>'organization_id')::integer;
  v_item_id := (p_params->>'item_id')::integer;
  PERFORM inv.fn_semantic_assert_org_access(p_user_id, v_org_id);
  IF v_item_id IS NULL THEN
    PERFORM portal.fn_semantic_raise('GS400', 'item_id is required');
  END IF;

  RETURN QUERY
  SELECT
    v.stock_lot_id,
    v.organization_id,
    v.item_id,
    v.item_number,
    v.location_code,
    v.bin_code,
    v.lot_number,
    v.qty_on_hand,
    v.unit_cost
  FROM inv.v_stock_lot v
  WHERE v.organization_id = v_org_id
    AND v.item_id = v_item_id
    AND v.qty_on_hand > 0
  ORDER BY v.received_at_utc
  LIMIT GREATEST(0, COALESCE(p_limit, 500));
END;
$$;

CREATE OR REPLACE FUNCTION inv.fn_semantic_list_supplier_items(
  p_user_id integer,
  p_params jsonb,
  p_limit integer
)
RETURNS SETOF portal.inv_supplier_item_row
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = inv, portal, pg_temp
AS $$
DECLARE
  v_org_id integer;
  v_item_id integer;
BEGIN
  v_org_id := (p_params->>'organization_id')::integer;
  v_item_id := (p_params->>'item_id')::integer;
  PERFORM inv.fn_semantic_assert_org_access(p_user_id, v_org_id);

  RETURN QUERY
  SELECT
    v.supplier_item_id,
    v.organization_id,
    v.item_id,
    v.item_number,
    v.supplier_code,
    v.supplier_part_number,
    v.preferred,
    v.lead_time_days,
    v.active
  FROM inv.v_supplier_item v
  WHERE v.organization_id = v_org_id
    AND (v_item_id IS NULL OR v.item_id = v_item_id)
  ORDER BY v.supplier_code, v.supplier_part_number
  LIMIT GREATEST(0, COALESCE(p_limit, 500));
END;
$$;
