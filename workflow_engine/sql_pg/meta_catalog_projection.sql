/*
  Catalogs as Meta classes (generic). See docs/meta-catalogs.md.

  A catalog kind binds one catalog table (portal.semantic_entity, wf.workflow_action, cfg.site, ...)
  to one Meta class whose fields are the table's columns, typed by platform catalog data types.
  After "Meta".sp_catalog_migrate(kind) every row is a Meta object and Meta is authoritative:

    - Meta -> table: writing a catalog object (generic object editor, sp_obj_insert/update, delete)
      projects the row into the table. Defaults the table assigns (serial ids, timestamps) are
      written back into the object.
    - table -> Meta: existing writers (register procedures, gateway, workers, seeds) still write the
      table; a row trigger keeps the object in step, so running code needs no change.
    - "Meta".fn_catalog_drift(kind) lists rows where table and Meta disagree, and
      "Meta".sp_catalog_project_all(kind) rewrites the table from Meta (Meta wins).

  The table stays the read surface (indexes, foreign keys, row types) for the gateway and workers.
  All functions run with a fixed search_path and UTC so values serialize the same for every caller.
*/

BEGIN;

INSERT INTO wf.data_type (name, version, status, kind, schema_json, content_hash)
SELECT v.name, '1.0', 'published', v.kind, v.schema_json, md5(v.schema_json::text)
FROM (VALUES
  ('platform/catalog/Text', 'string', '{"type":"string"}'::jsonb),
  ('platform/catalog/Integer', 'int', '{"type":"integer"}'::jsonb),
  ('platform/catalog/Decimal', 'number', '{"type":"number"}'::jsonb),
  ('platform/catalog/Boolean', 'bool', '{"type":"boolean"}'::jsonb),
  ('platform/catalog/Timestamp', 'datetime', '{"type":"string","format":"date-time"}'::jsonb),
  ('platform/catalog/Date', 'string', '{"type":"string","format":"date"}'::jsonb),
  ('platform/catalog/Document', 'any', '{}'::jsonb),
  ('platform/catalog/TextList', 'array', '{"type":"array","items":{"type":"string"}}'::jsonb),
  ('platform/catalog/IntegerList', 'array', '{"type":"array","items":{"type":"integer"}}'::jsonb)
) AS v(name, kind, schema_json)
WHERE NOT EXISTS (SELECT 1 FROM wf.data_type t WHERE t.name = v.name AND t.version = '1.0');

CREATE TABLE IF NOT EXISTS "Meta".catalog_kind (
  kind text PRIMARY KEY,
  class_id integer NOT NULL UNIQUE REFERENCES "Meta"."Classes" ("ID"),
  relation regclass NOT NULL UNIQUE,
  key_columns text[] NOT NULL,
  label_columns text[] NOT NULL,
  owner_app text NOT NULL DEFAULT 'goliath_app',
  migrated_at_utc timestamptz,
  views_stale boolean NOT NULL DEFAULT false
);
ALTER TABLE "Meta".catalog_kind ADD COLUMN IF NOT EXISTS views_stale boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS "Meta".catalog_row (
  kind text NOT NULL REFERENCES "Meta".catalog_kind (kind) ON DELETE CASCADE,
  row_key jsonb NOT NULL,
  obj_id integer NOT NULL UNIQUE REFERENCES "Meta"."Objs" ("ID") ON DELETE CASCADE,
  PRIMARY KEY (kind, row_key)
);

-- Data type for a column (array columns map to the list types).
CREATE OR REPLACE FUNCTION "Meta".fn_catalog_column_type(p_type regtype)
RETURNS text
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, pg_temp
AS $$
  SELECT CASE
    WHEN p_type IN ('smallint'::regtype, 'integer'::regtype, 'bigint'::regtype) THEN 'platform/catalog/Integer'
    WHEN p_type IN ('numeric'::regtype, 'real'::regtype, 'double precision'::regtype) THEN 'platform/catalog/Decimal'
    WHEN p_type = 'boolean'::regtype THEN 'platform/catalog/Boolean'
    WHEN p_type IN ('timestamp with time zone'::regtype, 'timestamp without time zone'::regtype) THEN 'platform/catalog/Timestamp'
    WHEN p_type = 'date'::regtype THEN 'platform/catalog/Date'
    WHEN p_type IN ('jsonb'::regtype, 'json'::regtype) THEN 'platform/catalog/Document'
    WHEN p_type IN ('smallint[]'::regtype, 'integer[]'::regtype, 'bigint[]'::regtype) THEN 'platform/catalog/IntegerList'
    WHEN p_type IN ('text[]'::regtype, 'character varying[]'::regtype) THEN 'platform/catalog/TextList'
    ELSE 'platform/catalog/Text'
  END;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_catalog_columns(p_relation regclass)
RETURNS TABLE (name text, type_name text, required boolean, has_default boolean, nullable boolean, ordinal int)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, pg_temp
AS $$
  SELECT a.attname::text,
         "Meta".fn_catalog_column_type(a.atttypid::regtype),
         a.attnotnull AND NOT a.atthasdef AND a.attidentity = '' AND a.attgenerated = '',
         a.atthasdef OR a.attidentity <> '' OR a.attgenerated <> '',
         NOT a.attnotnull,
         a.attnum::int
  FROM pg_attribute a
  WHERE a.attrelid = p_relation AND a.attnum > 0 AND NOT a.attisdropped
  ORDER BY a.attnum;
$$;

-- Object document for a table row: top-level nulls dropped, plus a readable Label.
CREATE OR REPLACE FUNCTION "Meta".fn_catalog_row_doc(p_kind text, p_row jsonb)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = pg_catalog, pg_temp
SET timezone = 'UTC'
AS $$
  SELECT COALESCE((SELECT jsonb_object_agg(e.key, e.value) FROM jsonb_each(p_row) e WHERE e.value <> 'null'::jsonb), '{}'::jsonb)
    || jsonb_build_object('Label', COALESCE(NULLIF((
         SELECT string_agg(p_row ->> c, ' ' ORDER BY o) FROM unnest(k.label_columns) WITH ORDINALITY u(c, o)
       ), ''), p_kind))
  FROM "Meta".catalog_kind k WHERE k.kind = p_kind;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_catalog_row_key(p_kind text, p_row jsonb)
RETURNS jsonb
LANGUAGE sql
STABLE
SET search_path = pg_catalog, pg_temp
AS $$
  SELECT jsonb_object_agg(c, p_row -> c) FROM "Meta".catalog_kind k, unnest(k.key_columns) c WHERE k.kind = p_kind;
$$;

-- Guard so a write in one direction does not echo back. Values: capture | project | delete:<obj>.
CREATE OR REPLACE FUNCTION "Meta".fn_catalog_sync_state()
RETURNS text
LANGUAGE sql
STABLE
SET search_path = pg_catalog, pg_temp
AS $$ SELECT COALESCE(current_setting('goliath.catalog_sync', true), '') $$;

DROP FUNCTION IF EXISTS "Meta".sp_catalog_register_kind(text, text, text, regclass, text[], text[], text);

/*
  Register (or refresh) a catalog kind: the class (under p_parent_class), one field per column,
  the published class type, its view, and the table trigger. Idempotent; new columns become fields.
*/
CREATE OR REPLACE FUNCTION "Meta".sp_catalog_register_kind(
  p_kind text,
  p_class_name text,
  p_parent_class text,
  p_relation regclass,
  p_key_columns text[],
  p_label_columns text[],
  p_owner_app text DEFAULT 'goliath_app',
  p_refresh_views boolean DEFAULT true
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_class int;
  v_parent int;
  v_label_type bigint;
  v_table text;
  v_changed boolean := false;
  v_n int;
  c record;
BEGIN
  IF p_key_columns IS NULL OR cardinality(p_key_columns) = 0 THEN
    RAISE EXCEPTION 'catalog kind % needs key columns', p_kind;
  END IF;
  IF EXISTS (
    SELECT 1 FROM unnest(p_key_columns || p_label_columns) x(c)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta".fn_catalog_columns(p_relation) f WHERE f.name = x.c)
  ) THEN
    RAISE EXCEPTION 'catalog kind %: key or label column missing on %', p_kind, p_relation;
  END IF;
  IF EXISTS (SELECT 1 FROM "Meta".catalog_kind k WHERE k.kind <> p_kind AND k.relation = p_relation) THEN
    RAISE EXCEPTION 'relation % is already bound to another catalog kind', p_relation;
  END IF;

  SELECT cl."ID" INTO v_parent FROM "Meta"."Classes" cl WHERE cl."Name" = p_parent_class;
  IF v_parent IS NULL THEN
    RAISE EXCEPTION 'parent class % is missing', p_parent_class;
  END IF;

  -- One view rebuild per registration (or per batch, see sp_catalog_refresh_views), not one per
  -- class or field insert.
  PERFORM set_config('goliath.meta_defer_view_refresh', 'on', true);
  v_table := 'Catalog' || replace(initcap(replace(replace(p_kind, '.', ' '), '_', ' ')), ' ', '');
  SELECT cl."ID" INTO v_class FROM "Meta"."Classes" cl WHERE cl."Name" = p_class_name;
  IF v_class IS NULL THEN
    INSERT INTO "Meta"."Classes" ("Name", "ParentID", "TableName")
    VALUES (p_class_name, v_parent, v_table)
    RETURNING "ID" INTO v_class;
    PERFORM "Meta".sp_backfill_all_class_hierarchies();
    v_changed := true;
  END IF;

  SELECT t.id INTO v_label_type FROM wf.data_type t WHERE t.name = 'platform/catalog/Text' AND t.version = '1.0';
  INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
  SELECT v_class, 'Label', v_label_type, true, 'Display label'
  WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = v_class AND f."Name" = 'Label');
  GET DIAGNOSTICS v_n = ROW_COUNT;
  v_changed := v_changed OR v_n > 0;

  FOR c IN SELECT * FROM "Meta".fn_catalog_columns(p_relation) LOOP
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_class, c.name, t.id, c.required, format('%s.%s', p_relation, c.name)
    FROM wf.data_type t
    WHERE t.name = c.type_name AND t.version = '1.0'
      AND NOT EXISTS (SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = v_class AND f."Name" = c.name);
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_changed := v_changed OR v_n > 0;
  END LOOP;
  PERFORM set_config('goliath.meta_defer_view_refresh', '', true);

  INSERT INTO "Meta".catalog_kind (kind, class_id, relation, key_columns, label_columns, owner_app)
  VALUES (p_kind, v_class, p_relation, p_key_columns, p_label_columns, p_owner_app)
  ON CONFLICT (kind) DO UPDATE SET
    class_id = EXCLUDED.class_id,
    relation = EXCLUDED.relation,
    key_columns = EXCLUDED.key_columns,
    label_columns = EXCLUDED.label_columns,
    owner_app = EXCLUDED.owner_app;

  -- Regenerating views rebuilds the whole class tree's views: only on change.
  IF v_changed
     OR (SELECT cl."TypeID" FROM "Meta"."Classes" cl WHERE cl."ID" = v_class) IS NULL
     OR to_regclass(format('"Meta".%I', "Meta".fn_class_view_name(v_class))) IS NULL THEN
    PERFORM "Meta".sp_meta_publish_class_type(v_class, false);
    IF p_refresh_views THEN
      PERFORM "Meta".sp_class_regenerate_views(v_class);
    ELSE
      UPDATE "Meta".catalog_kind k SET views_stale = true WHERE k.kind = p_kind;
    END IF;
  END IF;

  EXECUTE format('DROP TRIGGER IF EXISTS "TR_MetaCatalog_Capture" ON %s', p_relation);
  EXECUTE format(
    'CREATE TRIGGER "TR_MetaCatalog_Capture" AFTER INSERT OR UPDATE OR DELETE ON %s '
    'FOR EACH ROW EXECUTE FUNCTION "Meta".trg_catalog_capture(%L)',
    p_relation, p_kind
  );
  RETURN v_class;
END;
$$;

-- After registering kinds with p_refresh_views => false: one view rebuild for all of them.
CREATE OR REPLACE FUNCTION "Meta".sp_catalog_refresh_views()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_class int;
  v_n int;
BEGIN
  SELECT count(*), min(k.class_id) INTO v_n, v_class FROM "Meta".catalog_kind k WHERE k.views_stale;
  IF v_n > 0 THEN
    -- sp_class_regenerate_views rebuilds the whole tree under the class's root.
    PERFORM "Meta".sp_class_regenerate_views(v_class);
    UPDATE "Meta".catalog_kind k SET views_stale = false WHERE k.views_stale;
  END IF;
  RETURN v_n;
END;
$$;

-- table -> Meta for one row (insert or update). Returns the object id.
CREATE OR REPLACE FUNCTION "Meta".sp_catalog_capture_row(p_kind text, p_row jsonb, p_old_key jsonb DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET timezone = 'UTC'
AS $$
DECLARE
  v_kind "Meta".catalog_kind;
  v_key jsonb;
  v_obj int;
  v_doc jsonb;
  v_prev text := "Meta".fn_catalog_sync_state();
BEGIN
  SELECT * INTO v_kind FROM "Meta".catalog_kind k WHERE k.kind = p_kind;
  v_key := "Meta".fn_catalog_row_key(p_kind, p_row);
  v_doc := "Meta".fn_catalog_row_doc(p_kind, p_row);

  SELECT r.obj_id INTO v_obj FROM "Meta".catalog_row r
  WHERE r.kind = p_kind AND r.row_key = COALESCE(p_old_key, v_key);

  PERFORM set_config('goliath.catalog_sync', 'capture', true);
  IF v_obj IS NULL THEN
    v_obj := "Meta".sp_obj_insert(v_kind.class_id, v_doc);
    INSERT INTO "Meta".catalog_row (kind, row_key, obj_id) VALUES (p_kind, v_key, v_obj)
    ON CONFLICT (kind, row_key) DO UPDATE SET obj_id = EXCLUDED.obj_id;
  ELSE
    IF "Meta".fn_merged_obj_document(v_obj) IS DISTINCT FROM v_doc THEN
      PERFORM "Meta".sp_obj_update(v_obj, v_doc);
    END IF;
    IF p_old_key IS NOT NULL AND p_old_key IS DISTINCT FROM v_key THEN
      UPDATE "Meta".catalog_row r SET row_key = v_key WHERE r.kind = p_kind AND r.obj_id = v_obj;
    END IF;
  END IF;
  PERFORM set_config('goliath.catalog_sync', v_prev, true);
  RETURN v_obj;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_catalog_capture()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET timezone = 'UTC'
AS $$
DECLARE
  v_kind text := TG_ARGV[0];
  v_state text := "Meta".fn_catalog_sync_state();
  v_obj int;
  v_prev text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    SELECT r.obj_id INTO v_obj FROM "Meta".catalog_row r
    WHERE r.kind = v_kind AND r.row_key = "Meta".fn_catalog_row_key(v_kind, to_jsonb(OLD));
    -- The object being deleted from Meta removed this row itself; cascaded rows still go.
    IF v_obj IS NOT NULL AND v_state IS DISTINCT FROM 'delete:' || v_obj THEN
      v_prev := v_state;
      PERFORM set_config('goliath.catalog_sync', 'delete:' || v_obj, true);
      DELETE FROM "Meta"."Objs" o WHERE o."ID" = v_obj;
      PERFORM set_config('goliath.catalog_sync', v_prev, true);
    END IF;
    RETURN OLD;
  END IF;
  IF v_state = 'project' THEN
    RETURN NEW;
  END IF;
  PERFORM "Meta".sp_catalog_capture_row(
    v_kind,
    to_jsonb(NEW),
    CASE WHEN TG_OP = 'UPDATE' THEN "Meta".fn_catalog_row_key(v_kind, to_jsonb(OLD)) END
  );
  RETURN NEW;
END;
$$;

/*
  Meta -> table for one object. Inserts the row when the object has none yet (table defaults fill
  the rest and are written back into the object), else updates it; a column missing from the
  document becomes NULL when nullable and keeps its value otherwise.
*/
CREATE OR REPLACE FUNCTION "Meta".sp_catalog_project(p_kind text, p_obj_id integer)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET timezone = 'UTC'
AS $$
DECLARE
  v_kind "Meta".catalog_kind;
  v_doc jsonb;
  v_key jsonb;
  v_row jsonb;
  v_cols text;
  v_sets text;
  v_where text;
  v_prev text := "Meta".fn_catalog_sync_state();
BEGIN
  SELECT * INTO v_kind FROM "Meta".catalog_kind k WHERE k.kind = p_kind;
  v_doc := "Meta".fn_merged_obj_document(p_obj_id) - 'Label';
  SELECT r.row_key INTO v_key FROM "Meta".catalog_row r WHERE r.kind = p_kind AND r.obj_id = p_obj_id;

  PERFORM set_config('goliath.catalog_sync', 'project', true);
  IF v_key IS NULL THEN
    SELECT string_agg(format('%I', c.name), ', ' ORDER BY c.ordinal) INTO v_cols
    FROM "Meta".fn_catalog_columns(v_kind.relation) c WHERE v_doc ? c.name;
    EXECUTE format(
      'INSERT INTO %1$s AS t (%2$s) SELECT %2$s FROM jsonb_populate_record(NULL::%1$s, $1) RETURNING to_jsonb(t.*)',
      v_kind.relation, v_cols
    ) INTO v_row USING v_doc;
    v_key := "Meta".fn_catalog_row_key(p_kind, v_row);
    INSERT INTO "Meta".catalog_row (kind, row_key, obj_id) VALUES (p_kind, v_key, p_obj_id);
  ELSE
    SELECT string_agg(
             CASE WHEN v_doc ? c.name OR c.nullable THEN format('%1$I = s.%1$I', c.name) ELSE format('%1$I = t.%1$I', c.name) END,
             ', ' ORDER BY c.ordinal)
    INTO v_sets FROM "Meta".fn_catalog_columns(v_kind.relation) c;
    SELECT string_agg(format('t.%1$I = (SELECT k.%1$I FROM jsonb_populate_record(NULL::%2$s, $2) k)', c, v_kind.relation), ' AND ')
    INTO v_where FROM unnest(v_kind.key_columns) c;
    EXECUTE format(
      'UPDATE %1$s AS t SET %2$s FROM jsonb_populate_record(NULL::%1$s, $1) s WHERE %3$s RETURNING to_jsonb(t.*)',
      v_kind.relation, v_sets, v_where
    ) INTO v_row USING v_doc, v_key;
    IF v_row IS NULL THEN
      -- Row went missing from the table: Meta wins, insert it again.
      DELETE FROM "Meta".catalog_row r WHERE r.kind = p_kind AND r.obj_id = p_obj_id;
      PERFORM set_config('goliath.catalog_sync', v_prev, true);
      RETURN "Meta".sp_catalog_project(p_kind, p_obj_id);
    END IF;
    UPDATE "Meta".catalog_row r SET row_key = "Meta".fn_catalog_row_key(p_kind, v_row)
    WHERE r.kind = p_kind AND r.obj_id = p_obj_id AND r.row_key IS DISTINCT FROM "Meta".fn_catalog_row_key(p_kind, v_row);
  END IF;

  -- Write table-assigned values (ids, defaults) back into the object.
  IF "Meta".fn_catalog_row_doc(p_kind, v_row) - 'Label' IS DISTINCT FROM v_doc THEN
    PERFORM "Meta".sp_obj_update(p_obj_id, "Meta".fn_catalog_row_doc(p_kind, v_row));
  END IF;
  PERFORM set_config('goliath.catalog_sync', v_prev, true);
  RETURN v_row;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_catalog_project_values()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_kind text;
BEGIN
  IF "Meta".fn_catalog_sync_state() IN ('capture', 'project') THEN
    RETURN NEW;
  END IF;
  SELECT k.kind INTO v_kind
  FROM "Meta"."Objs" o JOIN "Meta".catalog_kind k ON k.class_id = o."ClassID"
  WHERE o."ID" = NEW."ObjID";
  IF v_kind IS NOT NULL THEN
    PERFORM "Meta".sp_catalog_project(v_kind, NEW."ObjID");
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_ObjValues_Catalog_Projection" ON "Meta"."ObjValues";
CREATE TRIGGER "TR_ObjValues_Catalog_Projection"
  AFTER INSERT OR UPDATE OF "Data" ON "Meta"."ObjValues"
  FOR EACH ROW EXECUTE FUNCTION "Meta".trg_catalog_project_values();

CREATE OR REPLACE FUNCTION "Meta".trg_catalog_obj_delete()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_kind "Meta".catalog_kind;
  v_key jsonb;
  v_where text;
  v_prev text;
BEGIN
  SELECT k.* INTO v_kind FROM "Meta".catalog_kind k WHERE k.class_id = OLD."ClassID";
  IF v_kind.kind IS NULL THEN
    RETURN OLD;
  END IF;
  SELECT r.row_key INTO v_key FROM "Meta".catalog_row r WHERE r.kind = v_kind.kind AND r.obj_id = OLD."ID";
  IF v_key IS NULL THEN
    RETURN OLD;
  END IF;
  v_prev := "Meta".fn_catalog_sync_state();
  PERFORM set_config('goliath.catalog_sync', 'delete:' || OLD."ID", true);
  SELECT string_agg(format('t.%1$I = (SELECT k.%1$I FROM jsonb_populate_record(NULL::%2$s, $1) k)', c, v_kind.relation), ' AND ')
  INTO v_where FROM unnest(v_kind.key_columns) c;
  EXECUTE format('DELETE FROM %s AS t WHERE %s', v_kind.relation, v_where) USING v_key;
  PERFORM set_config('goliath.catalog_sync', v_prev, true);
  RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS "TR_Objs_Catalog_Delete" ON "Meta"."Objs";
CREATE TRIGGER "TR_Objs_Catalog_Delete"
  BEFORE DELETE ON "Meta"."Objs"
  FOR EACH ROW EXECUTE FUNCTION "Meta".trg_catalog_obj_delete();

-- Every table row becomes (or refreshes) its Meta object; objects whose row is gone are removed.
CREATE OR REPLACE FUNCTION "Meta".sp_catalog_migrate(p_kind text)
RETURNS TABLE (kind text, table_rows bigint, objects bigint, removed bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET timezone = 'UTC'
AS $$
DECLARE
  v_kind "Meta".catalog_kind;
  v_row jsonb;
  v_rows bigint := 0;
  v_removed bigint := 0;
  v_obj int;
  v_prev text := "Meta".fn_catalog_sync_state();
BEGIN
  SELECT * INTO v_kind FROM "Meta".catalog_kind k WHERE k.kind = p_kind;
  IF v_kind.kind IS NULL THEN
    RAISE EXCEPTION 'unknown catalog kind %', p_kind;
  END IF;
  FOR v_row IN EXECUTE format('SELECT to_jsonb(t.*) FROM %s t', v_kind.relation) LOOP
    PERFORM "Meta".sp_catalog_capture_row(p_kind, v_row);
    v_rows := v_rows + 1;
  END LOOP;

  FOR v_obj IN
    SELECT r.obj_id FROM "Meta".catalog_row r
    WHERE r.kind = p_kind
      AND NOT EXISTS (SELECT 1 FROM "Meta".fn_catalog_table_keys(p_kind) t WHERE t.row_key = r.row_key)
  LOOP
    PERFORM set_config('goliath.catalog_sync', 'delete:' || v_obj, true);
    DELETE FROM "Meta"."Objs" o WHERE o."ID" = v_obj;
    v_removed := v_removed + 1;
  END LOOP;
  PERFORM set_config('goliath.catalog_sync', v_prev, true);

  UPDATE "Meta".catalog_kind k SET migrated_at_utc = now() WHERE k.kind = p_kind;
  RETURN QUERY SELECT p_kind, v_rows,
    (SELECT count(*) FROM "Meta".catalog_row r WHERE r.kind = p_kind), v_removed;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_catalog_table_keys(p_kind text)
RETURNS TABLE (row_key jsonb, row_doc jsonb)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET timezone = 'UTC'
AS $$
DECLARE
  v_kind "Meta".catalog_kind;
BEGIN
  SELECT * INTO v_kind FROM "Meta".catalog_kind k WHERE k.kind = p_kind;
  RETURN QUERY EXECUTE format(
    'SELECT "Meta".fn_catalog_row_key(%L, to_jsonb(t.*)), "Meta".fn_catalog_row_doc(%L, to_jsonb(t.*)) FROM %s t',
    p_kind, p_kind, v_kind.relation
  );
END;
$$;

/*
  Rows where the table and Meta disagree: missing_object (row without object), missing_row (object
  without row) or differs. Values are compared as typed table rows, so formatting does not matter.
*/
CREATE OR REPLACE FUNCTION "Meta".fn_catalog_drift(p_kind text DEFAULT NULL)
RETURNS TABLE (kind text, row_key jsonb, obj_id integer, issue text)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET timezone = 'UTC'
AS $$
DECLARE
  k "Meta".catalog_kind;
BEGIN
  FOR k IN SELECT * FROM "Meta".catalog_kind c WHERE p_kind IS NULL OR c.kind = p_kind ORDER BY c.kind LOOP
    RETURN QUERY EXECUTE format($q$
      WITH t AS (
        SELECT "Meta".fn_catalog_row_key(%1$L, to_jsonb(x.*)) AS row_key, x AS rec FROM %2$s x
      ), m AS (
        SELECT r.row_key, r.obj_id,
               jsonb_populate_record(NULL::%2$s, "Meta".fn_merged_obj_document(r.obj_id) - 'Label') AS rec
        FROM "Meta".catalog_row r WHERE r.kind = %1$L
      )
      SELECT %1$L::text, COALESCE(t.row_key, m.row_key), m.obj_id,
             CASE WHEN m.obj_id IS NULL THEN 'missing_object'
                  WHEN t.row_key IS NULL THEN 'missing_row'
                  ELSE 'differs' END
      FROM t FULL JOIN m ON m.row_key = t.row_key
      WHERE m.obj_id IS NULL OR t.row_key IS NULL OR t.rec IS DISTINCT FROM m.rec
    $q$, k.kind, k.relation);
  END LOOP;
END;
$$;

-- Meta wins: rewrite every row of the table from its object (repair after drift).
CREATE OR REPLACE FUNCTION "Meta".sp_catalog_project_all(p_kind text)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  v_obj int;
  v_n bigint := 0;
BEGIN
  FOR v_obj IN SELECT r.obj_id FROM "Meta".catalog_row r WHERE r.kind = p_kind ORDER BY r.obj_id LOOP
    PERFORM "Meta".sp_catalog_project(p_kind, v_obj);
    v_n := v_n + 1;
  END LOOP;
  RETURN v_n;
END;
$$;

REVOKE ALL ON FUNCTION "Meta".sp_catalog_register_kind(text, text, text, regclass, text[], text[], text, boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION "Meta".sp_catalog_refresh_views() FROM PUBLIC;
REVOKE ALL ON FUNCTION "Meta".sp_catalog_migrate(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION "Meta".sp_catalog_project_all(text) FROM PUBLIC;

COMMIT;
