-- Meta model Phase E (design: docs/meta-model.md §7)
-- Route legacy Meta.spInsertObject / spUpdateObject through ObjValues when Fields are declared.

CREATE OR REPLACE FUNCTION "Meta".spinsertobject(
  p_class_id int,
  p_values_json jsonb
)
RETURNS TABLE(new_id int)
LANGUAGE plpgsql
AS $$
DECLARE
  v_new_id int;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM "Meta"."Classes" WHERE "ID" = p_class_id) THEN
    RAISE EXCEPTION 'Class ID % not found.', p_class_id;
  END IF;

  IF EXISTS (SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = p_class_id)
     OR EXISTS (
       SELECT 1
       FROM "Meta"."ClassClosure" cc
       JOIN "Meta"."Fields" f ON f."ClassID" = cc."AncestorID"
       WHERE cc."DescendantID" = p_class_id
     ) THEN
    v_new_id := "Meta".sp_obj_insert(p_class_id, p_values_json);
    IF (SELECT "HasHistory" FROM "Meta"."Classes" WHERE "ID" = p_class_id) THEN
      PERFORM "Meta".sphistoryinsert(v_new_id, 1);
    END IF;
    RETURN QUERY SELECT v_new_id;
    RETURN;
  END IF;

  -- Legacy typed-table path (unchanged) when no Meta.Fields are declared.
  RETURN QUERY
  SELECT ni.new_id
  FROM "Meta".spinsertobject_legacy_typed_tables(p_class_id, p_values_json) ni;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".spinsertobject_legacy_typed_tables(
  p_class_id int,
  p_values_json jsonb
)
RETURNS TABLE(new_id int)
LANGUAGE plpgsql
AS $$
DECLARE
  v_new_id   int;
  v_table    text;
  v_cols     text;
  v_vals     text;
  v_sql      text;
  r          record;
BEGIN
  INSERT INTO "Meta"."Objs" ("ClassID") VALUES (p_class_id)
  RETURNING "ID" INTO v_new_id;

  FOR r IN
    WITH RECURSIVE hier AS (
      SELECT "ID", COALESCE("TableName", "Name") AS tname, "ParentID", 0 AS lvl
      FROM "Meta"."Classes" WHERE "ID" = p_class_id
      UNION ALL
      SELECT c."ID", COALESCE(c."TableName", c."Name"), c."ParentID", h.lvl + 1
      FROM "Meta"."Classes" c JOIN hier h ON c."ID" = h."ParentID"
    )
    SELECT tname AS table_name FROM hier WHERE tname <> 'Objs' ORDER BY lvl DESC
  LOOP
    v_table := r.table_name;
    SELECT
      string_agg(quote_ident(c.column_name), ', ' ORDER BY c.ordinal_position),
      string_agg('($1->>' || quote_literal(c.column_name) || ')::' || c.udt_name, ', ' ORDER BY c.ordinal_position)
    INTO v_cols, v_vals
    FROM information_schema.columns c
    WHERE c.table_schema = 'Meta' AND c.table_name = v_table
      AND c.column_name <> 'ID'
      AND p_values_json ? c.column_name;

    IF v_cols IS NOT NULL THEN
      v_sql := format(
        'INSERT INTO "Meta".%I ("ID", %s) VALUES ($2, %s) ON CONFLICT ("ID") DO UPDATE SET (%s) = (%s)',
        v_table, v_cols, v_vals, v_cols, v_vals
      );
      EXECUTE v_sql USING p_values_json, v_new_id;
    END IF;
  END LOOP;

  RETURN QUERY SELECT v_new_id;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".spupdateobject(
  p_class_id int,
  p_id int,
  p_values_json jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM "Meta"."Objs" WHERE "ID" = p_id) THEN
    RAISE EXCEPTION 'Object % does not exist.', p_id;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM "Meta"."Classes" WHERE "ID" = p_class_id) THEN
    RAISE EXCEPTION 'Class ID % not found.', p_class_id;
  END IF;

  IF EXISTS (SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = p_class_id)
     OR EXISTS (
       SELECT 1
       FROM "Meta"."ClassClosure" cc
       JOIN "Meta"."Fields" f ON f."ClassID" = cc."AncestorID"
       WHERE cc."DescendantID" = p_class_id
     ) THEN
    PERFORM "Meta".sp_obj_update(p_id, p_values_json);
    IF (SELECT "HasHistory" FROM "Meta"."Classes" WHERE "ID" = p_class_id) THEN
      PERFORM "Meta".sphistoryinsert(p_id, 2);
    END IF;
    RETURN;
  END IF;

  PERFORM "Meta".spupdateobject_legacy_typed_tables(p_class_id, p_id, p_values_json);
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".spupdateobject_legacy_typed_tables(
  p_class_id int,
  p_id int,
  p_values_json jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_sql   text;
  v_set   text;
  r       record;
BEGIN
  FOR r IN
    WITH RECURSIVE hier AS (
      SELECT "ID", COALESCE("TableName", "Name") AS tname, "ParentID", 0 AS lvl
      FROM "Meta"."Classes" WHERE "ID" = p_class_id
      UNION ALL
      SELECT c."ID", COALESCE(c."TableName", c."Name"), c."ParentID", h.lvl + 1
      FROM "Meta"."Classes" c JOIN hier h ON c."ID" = h."ParentID"
    )
    SELECT tname AS table_name FROM hier WHERE tname <> 'Objs' ORDER BY lvl DESC
  LOOP
    SELECT string_agg(
      quote_ident(c.column_name) || ' = ($1->>' || quote_literal(c.column_name) || ')::' || c.udt_name,
      ', ' ORDER BY c.ordinal_position
    )
    INTO v_set
    FROM information_schema.columns c
    WHERE c.table_schema = 'Meta' AND c.table_name = r.table_name
      AND c.column_name <> 'ID'
      AND p_values_json ? c.column_name;

    IF v_set IS NOT NULL THEN
      v_sql := format('UPDATE "Meta".%I SET %s WHERE "ID" = $2', r.table_name, v_set);
      EXECUTE v_sql USING p_values_json, p_id;
    END IF;
  END LOOP;
END;
$$;

COMMENT ON FUNCTION "Meta".spinsertobject(int, jsonb) IS
  'Inserts via Meta.ObjValues when Fields exist; otherwise legacy typed tables (meta-model Phase E).';
