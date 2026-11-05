-- Inventory module write APIs (organization-scoped). Child apps call these from workflows or extend with domain actions.

CREATE OR REPLACE FUNCTION inv.fn_assert_org_member(
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
  IF p_user_id IS NULL OR p_organization_id IS NULL THEN
    RAISE EXCEPTION 'user_id and organization_id are required';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM portal."OrganizationMembers" m
    WHERE m."UserID" = p_user_id
      AND m."OrganizationID" = p_organization_id
  ) THEN
    RAISE EXCEPTION 'organization scope denied';
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION inv.fn_supplier_approved_for_item(
  p_organization_id integer,
  p_supplier_id integer,
  p_item_id integer
)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = inv, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM inv.approved_supplier a
    WHERE a.organization_id = p_organization_id
      AND a.supplier_id = p_supplier_id
      AND (a.item_id IS NULL OR a.item_id = p_item_id)
      AND a.approved_from <= CURRENT_DATE
      AND (a.approved_to IS NULL OR a.approved_to >= CURRENT_DATE)
  );
$$;

CREATE OR REPLACE FUNCTION inv.fn_item_qty_on_hand(p_item_id integer)
RETURNS numeric
LANGUAGE sql
STABLE
SET search_path = inv, pg_temp
AS $$
  SELECT COALESCE(sum(s.qty_on_hand), 0)
  FROM inv.stock_lot s
  WHERE s.item_id = p_item_id;
$$;

CREATE OR REPLACE FUNCTION inv.fn_apply_moving_average(
  p_item_id integer,
  p_recv_qty numeric,
  p_recv_unit_cost numeric
)
RETURNS numeric
LANGUAGE plpgsql
SET search_path = inv, pg_temp
AS $$
DECLARE
  v_old_qty numeric;
  v_old_avg numeric;
  v_new_avg numeric;
BEGIN
  v_old_qty := inv.fn_item_qty_on_hand(p_item_id);
  SELECT i.avg_unit_cost INTO v_old_avg FROM inv.item i WHERE i.item_id = p_item_id FOR UPDATE;
  IF v_old_qty + p_recv_qty = 0 THEN
    v_new_avg := 0;
  ELSE
    v_new_avg := (v_old_qty * v_old_avg + p_recv_qty * p_recv_unit_cost) / (v_old_qty + p_recv_qty);
  END IF;
  UPDATE inv.item
  SET avg_unit_cost = v_new_avg
  WHERE item_id = p_item_id;
  INSERT INTO inv.item_cost_snapshot (item_id, avg_unit_cost, qty_on_hand)
  VALUES (p_item_id, v_new_avg, v_old_qty + p_recv_qty);
  RETURN v_new_avg;
END;
$$;

CREATE OR REPLACE FUNCTION inv.fn_resolve_receipt_unit_cost(
  p_item_id integer,
  p_unit_price numeric
)
RETURNS numeric
LANGUAGE plpgsql
STABLE
SET search_path = inv, pg_temp
AS $$
DECLARE
  v_method text;
  v_standard numeric;
BEGIN
  SELECT i.costing_method, i.standard_unit_cost
  INTO v_method, v_standard
  FROM inv.item i
  WHERE i.item_id = p_item_id;
  IF v_method = 'standard' AND v_standard IS NOT NULL THEN
    RETURN v_standard;
  END IF;
  RETURN COALESCE(p_unit_price, 0);
END;
$$;

CREATE OR REPLACE FUNCTION inv.sp_stock_receive(
  p_organization_id integer,
  p_user_id integer,
  p_po_line_id integer,
  p_bin_id integer,
  p_qty numeric,
  p_lot_number text DEFAULT NULL,
  p_unit_price_override numeric DEFAULT NULL,
  OUT receipt_id integer,
  OUT stock_lot_id integer,
  OUT avg_unit_cost numeric
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = inv, portal, pg_temp
AS $$
DECLARE
  v_org_id integer;
  v_supplier_id integer;
  v_item_id integer;
  v_unit_price numeric;
  v_unit_cost numeric;
  v_po_id integer;
  v_costing_method text;
BEGIN
  PERFORM inv.fn_assert_org_member(p_user_id, p_organization_id);
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RAISE EXCEPTION 'qty must be positive';
  END IF;

  SELECT po.organization_id, po.supplier_id, pol.item_id, pol.unit_price, po.purchase_order_id
  INTO v_org_id, v_supplier_id, v_item_id, v_unit_price, v_po_id
  FROM inv.purchase_order_line pol
  INNER JOIN inv.purchase_order po ON po.purchase_order_id = pol.purchase_order_id
  WHERE pol.po_line_id = p_po_line_id
  FOR UPDATE OF pol;

  IF v_org_id IS DISTINCT FROM p_organization_id THEN
    RAISE EXCEPTION 'purchase order line not in organization';
  END IF;

  IF NOT inv.fn_supplier_approved_for_item(p_organization_id, v_supplier_id, v_item_id) THEN
    RAISE EXCEPTION 'supplier not on approved supplier list for item';
  END IF;

  IF (
    SELECT pol.qty_received + p_qty > pol.qty_ordered
    FROM inv.purchase_order_line pol
    WHERE pol.po_line_id = p_po_line_id
  ) THEN
    RAISE EXCEPTION 'receive qty exceeds PO line open quantity';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM inv.bin b
    INNER JOIN inv.location l ON l.location_id = b.location_id
    WHERE b.bin_id = p_bin_id AND l.organization_id = p_organization_id
  ) THEN
    RAISE EXCEPTION 'bin not in organization';
  END IF;

  v_unit_cost := inv.fn_resolve_receipt_unit_cost(
    v_item_id,
    COALESCE(p_unit_price_override, v_unit_price)
  );

  INSERT INTO inv.stock_lot (
    organization_id, item_id, bin_id, lot_number, qty_on_hand, unit_cost
  )
  VALUES (
    p_organization_id, v_item_id, p_bin_id, p_lot_number, p_qty, v_unit_cost
  )
  RETURNING inv.stock_lot.stock_lot_id INTO stock_lot_id;

  INSERT INTO inv.receipt (
    organization_id, po_line_id, stock_lot_id, qty_received, received_by_user_id
  )
  VALUES (
    p_organization_id, p_po_line_id, stock_lot_id, p_qty, p_user_id
  )
  RETURNING inv.receipt.receipt_id INTO receipt_id;

  UPDATE inv.purchase_order_line
  SET qty_received = qty_received + p_qty
  WHERE po_line_id = p_po_line_id;

  UPDATE inv.purchase_order po
  SET status = CASE
    WHEN (
      SELECT bool_and(pol.qty_received >= pol.qty_ordered)
      FROM inv.purchase_order_line pol
      WHERE pol.purchase_order_id = po.purchase_order_id
    ) THEN 'closed'
    ELSE 'partial'
  END
  WHERE po.purchase_order_id = v_po_id;

  SELECT i.costing_method INTO v_costing_method FROM inv.item i WHERE i.item_id = v_item_id;
  IF v_costing_method = 'moving_average' THEN
    avg_unit_cost := inv.fn_apply_moving_average(v_item_id, p_qty, v_unit_cost);
  ELSE
    avg_unit_cost := v_unit_cost;
  END IF;

  INSERT INTO inv.stock_move (
    organization_id, item_id, stock_lot_id, move_type, qty_delta, unit_cost,
    ref_type, ref_id, created_by_user_id
  )
  VALUES (
    p_organization_id, v_item_id, stock_lot_id, 'receive', p_qty, v_unit_cost,
    'receipt', receipt_id::text, p_user_id
  );
END;
$$;

CREATE OR REPLACE FUNCTION inv.sp_stock_adjust(
  p_organization_id integer,
  p_user_id integer,
  p_stock_lot_id integer,
  p_qty_delta numeric,
  p_reason_code text,
  OUT adjustment_id integer,
  OUT qty_on_hand numeric
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = inv, portal, pg_temp
AS $$
DECLARE
  v_item_id integer;
  v_org_id integer;
BEGIN
  PERFORM inv.fn_assert_org_member(p_user_id, p_organization_id);
  IF p_qty_delta IS NULL OR p_qty_delta = 0 THEN
    RAISE EXCEPTION 'qty_delta must be non-zero';
  END IF;
  IF p_reason_code IS NULL OR btrim(p_reason_code) = '' THEN
    RAISE EXCEPTION 'reason_code is required';
  END IF;

  SELECT s.organization_id, s.item_id, s.qty_on_hand
  INTO v_org_id, v_item_id, qty_on_hand
  FROM inv.stock_lot s
  WHERE s.stock_lot_id = p_stock_lot_id
  FOR UPDATE;

  IF v_org_id IS DISTINCT FROM p_organization_id THEN
    RAISE EXCEPTION 'stock lot not in organization';
  END IF;

  IF qty_on_hand + p_qty_delta < 0 THEN
    RAISE EXCEPTION 'adjustment would make qty_on_hand negative';
  END IF;

  UPDATE inv.stock_lot
  SET qty_on_hand = qty_on_hand + p_qty_delta
  WHERE stock_lot_id = p_stock_lot_id
  RETURNING inv.stock_lot.qty_on_hand INTO qty_on_hand;

  INSERT INTO inv.stock_adjustment (
    organization_id, item_id, stock_lot_id, qty_delta, reason_code, created_by_user_id
  )
  VALUES (
    p_organization_id, v_item_id, p_stock_lot_id, p_qty_delta, btrim(p_reason_code), p_user_id
  )
  RETURNING inv.stock_adjustment.adjustment_id INTO adjustment_id;

  INSERT INTO inv.stock_move (
    organization_id, item_id, stock_lot_id, move_type, qty_delta, unit_cost,
    reason_code, created_by_user_id
  )
  SELECT
    p_organization_id,
    v_item_id,
    p_stock_lot_id,
    'adjust',
    p_qty_delta,
    s.unit_cost,
    btrim(p_reason_code),
    p_user_id
  FROM inv.stock_lot s
  WHERE s.stock_lot_id = p_stock_lot_id;
END;
$$;

-- Domain-neutral issue stub: decrements lot qty and records an opaque ref for child genealogy wiring.
CREATE OR REPLACE FUNCTION inv.sp_stock_issue_stub(
  p_organization_id integer,
  p_user_id integer,
  p_stock_lot_id integer,
  p_qty numeric,
  p_ref_type text,
  p_ref_id text,
  OUT stock_move_id bigint,
  OUT qty_on_hand numeric
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = inv, portal, pg_temp
AS $$
DECLARE
  v_item_id integer;
  v_org_id integer;
  v_unit_cost numeric;
BEGIN
  PERFORM inv.fn_assert_org_member(p_user_id, p_organization_id);
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RAISE EXCEPTION 'qty must be positive';
  END IF;
  IF p_ref_type IS NULL OR btrim(p_ref_type) = '' OR p_ref_id IS NULL OR btrim(p_ref_id) = '' THEN
    RAISE EXCEPTION 'ref_type and ref_id are required';
  END IF;

  SELECT s.organization_id, s.item_id, s.qty_on_hand, s.unit_cost
  INTO v_org_id, v_item_id, qty_on_hand, v_unit_cost
  FROM inv.stock_lot s
  WHERE s.stock_lot_id = p_stock_lot_id
  FOR UPDATE;

  IF v_org_id IS DISTINCT FROM p_organization_id THEN
    RAISE EXCEPTION 'stock lot not in organization';
  END IF;
  IF qty_on_hand < p_qty THEN
    RAISE EXCEPTION 'insufficient qty on hand';
  END IF;

  UPDATE inv.stock_lot
  SET qty_on_hand = qty_on_hand - p_qty
  WHERE stock_lot_id = p_stock_lot_id
  RETURNING inv.stock_lot.qty_on_hand INTO qty_on_hand;

  INSERT INTO inv.stock_move (
    organization_id, item_id, stock_lot_id, move_type, qty_delta, unit_cost,
    ref_type, ref_id, created_by_user_id
  )
  VALUES (
    p_organization_id, v_item_id, p_stock_lot_id, 'issue', -p_qty, v_unit_cost,
    btrim(p_ref_type), btrim(p_ref_id), p_user_id
  )
  RETURNING inv.stock_move.stock_move_id INTO stock_move_id;
END;
$$;

CREATE OR REPLACE FUNCTION inv.sp_create_reservation(
  p_organization_id integer,
  p_user_id integer,
  p_item_id integer,
  p_stock_lot_id integer,
  p_qty numeric,
  p_ref_type text,
  p_ref_id text,
  OUT reservation_id integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = inv, portal, pg_temp
AS $$
DECLARE
  v_org_id integer;
  v_lot_qty numeric;
BEGIN
  PERFORM inv.fn_assert_org_member(p_user_id, p_organization_id);
  IF p_qty IS NULL OR p_qty <= 0 THEN
    RAISE EXCEPTION 'qty must be positive';
  END IF;

  SELECT i.organization_id INTO v_org_id FROM inv.item i WHERE i.item_id = p_item_id;
  IF v_org_id IS DISTINCT FROM p_organization_id THEN
    RAISE EXCEPTION 'item not in organization';
  END IF;

  IF p_stock_lot_id IS NOT NULL THEN
    SELECT s.qty_on_hand, s.organization_id
    INTO v_lot_qty, v_org_id
    FROM inv.stock_lot s
    WHERE s.stock_lot_id = p_stock_lot_id
    FOR UPDATE;
    IF v_org_id IS DISTINCT FROM p_organization_id THEN
      RAISE EXCEPTION 'stock lot not in organization';
    END IF;
    IF v_lot_qty < p_qty THEN
      RAISE EXCEPTION 'insufficient qty on lot';
    END IF;
  END IF;

  INSERT INTO inv.stock_reservation (
    organization_id, item_id, stock_lot_id, qty_reserved, ref_type, ref_id
  )
  VALUES (
    p_organization_id, p_item_id, p_stock_lot_id, p_qty, btrim(p_ref_type), btrim(p_ref_id)
  )
  RETURNING inv.stock_reservation.reservation_id INTO reservation_id;

  INSERT INTO inv.stock_move (
    organization_id, item_id, stock_lot_id, move_type, qty_delta, ref_type, ref_id, created_by_user_id
  )
  VALUES (
    p_organization_id, p_item_id, p_stock_lot_id, 'reserve', p_qty, btrim(p_ref_type), btrim(p_ref_id), p_user_id
  );
END;
$$;
