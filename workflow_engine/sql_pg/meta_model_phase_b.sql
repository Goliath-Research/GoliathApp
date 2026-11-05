-- Meta model Phase B (design: docs/meta-model.md §4.2, §5, §2.3 parameter schema)
-- JSON Schema generation, catalog publish, polymorphic class views (D5).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE VIEW "Meta"."VClassFieldsResolved" AS
SELECT DISTINCT ON (cc."DescendantID", f."Name")
  cc."DescendantID" AS "ClassID",
  f."ID",
  f."ClassID" AS "DeclaredOnClassID",
  f."Name",
  f."TypeID",
  f."Required",
  f."IsHot",
  f."Description",
  cc."Depth" AS "DefinedAtDepth"
FROM "Meta"."ClassClosure" cc
JOIN "Meta"."Fields" f ON f."ClassID" = cc."AncestorID"
ORDER BY cc."DescendantID", f."Name", cc."Depth" DESC;

CREATE OR REPLACE FUNCTION "Meta".fn_type_schema_uri(p_type_id bigint)
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT 'goliath:type/' || t.name
  FROM wf.data_type t
  WHERE t.id = p_type_id;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_class_schema_uri(p_class_id int)
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT 'goliath:meta/class/' || c."Name"
  FROM "Meta"."Classes" c
  WHERE c."ID" = p_class_id;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_effective_type_fragment(p_type_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_own jsonb;
  v_base bigint;
  v_base_frag jsonb;
BEGIN
  SELECT t.schema_json, t.base_type_id
  INTO v_own, v_base
  FROM wf.data_type t
  WHERE t.id = p_type_id;

  IF v_base IS NULL THEN
    RETURN COALESCE(v_own, jsonb_build_object('type', 'string'));
  END IF;

  v_base_frag := "Meta".fn_effective_type_fragment(v_base);
  IF v_own IS NULL OR v_own = '{}'::jsonb THEN
    RETURN v_base_frag;
  END IF;
  RETURN jsonb_build_object('allOf', jsonb_build_array(v_base_frag, v_own));
END;
$$;

DROP FUNCTION IF EXISTS "Meta".fn_class_json_schema(int);

CREATE OR REPLACE FUNCTION "Meta".fn_class_json_schema(p_class_id int, p_as_base boolean DEFAULT false)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_class record;
  v_parent_id int;
  v_props jsonb := '{}'::jsonb;
  v_required jsonb := '[]'::jsonb;
  v_allof jsonb := '[]'::jsonb;
  v_schema jsonb;
  r record;
BEGIN
  SELECT c."ID", c."Name", c."ParentID"
  INTO v_class
  FROM "Meta"."Classes" c
  WHERE c."ID" = p_class_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'class % not found', p_class_id;
  END IF;

  v_parent_id := v_class."ParentID";
  IF v_parent_id IS NOT NULL THEN
    v_allof := v_allof || jsonb_build_array(
      jsonb_build_object('$ref', "Meta".fn_class_schema_uri(v_parent_id))
    );
  END IF;

  FOR r IN
    SELECT fr."Name", fr."TypeID", fr."Required"
    FROM "Meta"."VClassFieldsResolved" fr
    WHERE fr."ClassID" = p_class_id
      AND fr."DeclaredOnClassID" = p_class_id
    ORDER BY fr."Name"
  LOOP
    v_props := v_props || jsonb_build_object(
      r."Name",
      jsonb_build_object('$ref', "Meta".fn_type_schema_uri(r."TypeID"))
    );
    IF r."Required" THEN
      v_required := v_required || to_jsonb(r."Name");
    END IF;
  END LOOP;

  v_schema := jsonb_build_object(
    '$schema', 'https://json-schema.org/draft/2020-12/schema',
    '$id', "Meta".fn_class_schema_uri(p_class_id),
    'allOf', v_allof,
    'type', 'object',
    'properties', v_props,
    'required', v_required
  );
  IF NOT p_as_base THEN
    v_schema := v_schema || jsonb_build_object('unevaluatedProperties', false);
  END IF;
  RETURN v_schema;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_class_json_schema_bundled(p_class_id int)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_schema jsonb;
  v_defs jsonb := '{}'::jsonb;
  r record;
  v_type_schema jsonb;
BEGIN
  v_schema := "Meta".fn_class_json_schema(p_class_id);

  FOR r IN
    SELECT DISTINCT fr."TypeID"
    FROM "Meta"."VClassFieldsResolved" fr
    WHERE fr."ClassID" = p_class_id
  LOOP
    v_type_schema := "Meta".fn_effective_type_fragment(r."TypeID");
    v_defs := v_defs || jsonb_build_object(
      "Meta".fn_type_schema_uri(r."TypeID"),
      v_type_schema
    );
  END LOOP;

  -- Inline ancestor class schemas for bundled validation.
  FOR r IN
    SELECT cc."AncestorID" AS class_id
    FROM "Meta"."ClassClosure" cc
    WHERE cc."DescendantID" = p_class_id
      AND cc."AncestorID" <> p_class_id
    ORDER BY cc."Depth"
  LOOP
    v_defs := v_defs || jsonb_build_object(
      "Meta".fn_class_schema_uri(r.class_id),
      "Meta".fn_class_json_schema(r.class_id, true)
    );
  END LOOP;

  RETURN v_schema || jsonb_build_object('$defs', v_defs);
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_method_params_json_schema(p_method_id int)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_method record;
  v_props jsonb := '{}'::jsonb;
  v_required jsonb := '[]'::jsonb;
  r record;
BEGIN
  SELECT m."ID", m."ClassID", m."Name", c."Name" AS class_name
  INTO v_method
  FROM "Meta"."Methods" m
  JOIN "Meta"."Classes" c ON c."ID" = m."ClassID"
  WHERE m."ID" = p_method_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'method % not found', p_method_id;
  END IF;

  FOR r IN
    SELECT mp."Name", mp."TypeID", mp."Required", mp."DefaultValue", mp."Ordinal"
    FROM "Meta"."MethodParams" mp
    WHERE mp."MethodID" = p_method_id
    ORDER BY mp."Ordinal"
  LOOP
    v_props := v_props || jsonb_build_object(
      r."Name",
      jsonb_strip_nulls(
        jsonb_build_object(
          '$ref', "Meta".fn_type_schema_uri(r."TypeID"),
          'default', r."DefaultValue"
        )
      )
    );
    IF r."Required" THEN
      v_required := v_required || to_jsonb(r."Name");
    END IF;
  END LOOP;

  RETURN jsonb_build_object(
    '$schema', 'https://json-schema.org/draft/2020-12/schema',
    '$id', format('goliath:meta/class/%s/%s.Params', v_method.class_name, v_method."Name"),
    'type', 'object',
    'properties', v_props,
    'required', v_required,
    'unevaluatedProperties', false
  );
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_meta_schema_content_hash(p_schema jsonb)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT encode(digest(p_schema::text, 'sha256'), 'hex');
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_bump_type_version(p_current text, p_breaking boolean)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  v_major int;
  v_minor int;
BEGIN
  IF p_current ~ '^[0-9]+\.[0-9]+$' THEN
    v_major := split_part(p_current, '.', 1)::int;
    v_minor := split_part(p_current, '.', 2)::int;
  ELSE
    v_major := COALESCE(NULLIF(regexp_replace(p_current, '[^0-9].*', ''), '')::int, 1);
    v_minor := 0;
  END IF;

  IF p_breaking THEN
    RETURN (v_major + 1)::text || '.0';
  END IF;
  RETURN v_major::text || '.' || (v_minor + 1)::text;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".sp_meta_publish_class_type(p_class_id int, p_breaking boolean DEFAULT false)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
  v_class record;
  v_schema jsonb;
  v_hash text;
  v_type_name text;
  v_version text;
  v_existing_version text;
  v_type_id bigint;
BEGIN
  SELECT c."ID", c."Name", c."TypeID"
  INTO v_class
  FROM "Meta"."Classes" c
  WHERE c."ID" = p_class_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'class % not found', p_class_id;
  END IF;

  v_schema := "Meta".fn_class_json_schema(p_class_id);
  v_hash := "Meta".fn_meta_schema_content_hash("Meta".fn_class_json_schema_bundled(p_class_id));
  v_type_name := 'meta/class/' || v_class."Name";

  IF v_class."TypeID" IS NOT NULL THEN
    SELECT t.version INTO v_existing_version
    FROM wf.data_type t
    WHERE t.id = v_class."TypeID";

    IF EXISTS (
      SELECT 1 FROM wf.data_type t
      WHERE t.id = v_class."TypeID" AND t.content_hash IS NOT DISTINCT FROM v_hash
    ) THEN
      RETURN v_class."TypeID";
    END IF;

    v_version := "Meta".fn_bump_type_version(COALESCE(v_existing_version, '1.0'), p_breaking);
  ELSE
    v_version := '1.0';
  END IF;

  SELECT dt.id INTO v_type_id
  FROM wf.wf_repo_upsert_data_type(
    v_type_name,
    v_version,
    'published',
    'object',
    NULL,
    NULL,
    v_hash,
    v_schema
  ) dt;

  UPDATE wf.data_type t
  SET class_id = p_class_id,
      description = COALESCE(t.description, format('Meta class %s', v_class."Name"))
  WHERE t.id = v_type_id;

  UPDATE "Meta"."Classes" c
  SET "TypeID" = v_type_id
  WHERE c."ID" = p_class_id;

  RETURN v_type_id;
END;
$$;

DROP FUNCTION IF EXISTS "Meta".sp_meta_publish_method_params_type(int);

CREATE OR REPLACE FUNCTION "Meta".sp_meta_publish_method_params_type(
  p_method_id int,
  p_breaking boolean DEFAULT false
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
  v_method record;
  v_schema jsonb;
  v_hash text;
  v_type_name text;
  v_version text;
  v_existing_version text;
  v_existing_type_id bigint;
  v_type_id bigint;
BEGIN
  SELECT m."ID", m."ClassID", m."Name", c."Name" AS class_name
  INTO v_method
  FROM "Meta"."Methods" m
  JOIN "Meta"."Classes" c ON c."ID" = m."ClassID"
  WHERE m."ID" = p_method_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'method % not found', p_method_id;
  END IF;

  v_schema := "Meta".fn_method_params_json_schema(p_method_id);
  v_hash := "Meta".fn_meta_schema_content_hash(v_schema);
  v_type_name := format('meta/class/%s/%s.Params', v_method.class_name, v_method."Name");

  SELECT t.id, t.version
  INTO v_existing_type_id, v_existing_version
  FROM wf.data_type t
  WHERE t.name = v_type_name
  ORDER BY
    CASE WHEN t.version ~ '^[0-9]+\.[0-9]+$' THEN split_part(t.version, '.', 1)::int ELSE 0 END DESC,
    CASE WHEN t.version ~ '^[0-9]+\.[0-9]+$' THEN split_part(t.version, '.', 2)::int ELSE 0 END DESC,
    t.id DESC
  LIMIT 1;

  IF v_existing_type_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM wf.data_type t
    WHERE t.id = v_existing_type_id AND t.content_hash IS NOT DISTINCT FROM v_hash
  ) THEN
    RETURN v_existing_type_id;
  END IF;

  IF v_existing_type_id IS NOT NULL THEN
    v_version := "Meta".fn_bump_type_version(COALESCE(v_existing_version, '1.0'), p_breaking);
  ELSE
    v_version := '1.0';
  END IF;

  SELECT dt.id INTO v_type_id
  FROM wf.wf_repo_upsert_data_type(
    v_type_name,
    v_version,
    'published',
    'object',
    NULL,
    NULL,
    v_hash,
    v_schema
  ) dt;

  RETURN v_type_id;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_class_view_name(p_class_id int)
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT 'V' || COALESCE(NULLIF(c."TableName", ''), c."Name")
  FROM "Meta"."Classes" c
  WHERE c."ID" = p_class_id;
$$;

CREATE OR REPLACE FUNCTION "Meta".sp_class_regenerate_views(p_class_id int)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_root int;
  v_id int;
  v_parent int;
  v_view text;
  v_parent_view text;
  v_field_select text;
  v_sql text;
  v_ord int;
BEGIN
  IF p_class_id IS NULL THEN
    RETURN;
  END IF;

  WITH RECURSIVE up AS (
    SELECT c."ID", c."ParentID"
    FROM "Meta"."Classes" c
    WHERE c."ID" = p_class_id
    UNION ALL
    SELECT p."ID", p."ParentID"
    FROM "Meta"."Classes" p
    JOIN up ON up."ParentID" = p."ID"
  )
  SELECT u."ID" INTO v_root FROM up u WHERE u."ParentID" IS NULL LIMIT 1;

  IF v_root IS NULL THEN
    v_root := p_class_id;
  END IF;

  CREATE TEMP TABLE IF NOT EXISTS _meta_view_order (
    class_id int PRIMARY KEY,
    ord int NOT NULL
  ) ON COMMIT DROP;
  TRUNCATE _meta_view_order;

  WITH RECURSIVE sub AS (
    SELECT c."ID", 0 AS depth_ord
    FROM "Meta"."Classes" c
    WHERE c."ID" = v_root
    UNION ALL
    SELECT c."ID", sub.depth_ord + 1
    FROM "Meta"."Classes" c
    JOIN sub ON c."ParentID" = sub."ID"
  )
  INSERT INTO _meta_view_order (class_id, ord)
  SELECT "ID", depth_ord FROM sub;

  FOR v_id, v_ord IN
    SELECT mvo.class_id, mvo.ord FROM _meta_view_order mvo ORDER BY mvo.ord
  LOOP
    SELECT c."ParentID", "Meta".fn_class_view_name(c."ID")
    INTO v_parent, v_view
    FROM "Meta"."Classes" c
    WHERE c."ID" = v_id;

    SELECT string_agg(
      format('(v_%s."Data"->>%L)::text AS %I', v_id, fr."Name", fr."Name"),
      E',\n  '
      ORDER BY fr."Name"
    )
    INTO v_field_select
    FROM "Meta"."VClassFieldsResolved" fr
    WHERE fr."ClassID" = v_id
      AND fr."DeclaredOnClassID" = v_id;

    IF v_parent IS NULL THEN
      v_sql := format(
        'CREATE OR REPLACE VIEW "Meta".%I AS
SELECT o."ID"%s
FROM "Meta"."Objs" o
JOIN "Meta"."ClassClosure" cc
  ON cc."DescendantID" = o."ClassID" AND cc."AncestorID" = %s%s',
        v_view,
        CASE WHEN v_field_select IS NOT NULL THEN E',\n  ' || v_field_select ELSE '' END,
        v_id,
        CASE
          WHEN v_field_select IS NOT NULL THEN format(
            E'\nLEFT JOIN "Meta"."ObjValues" v_%s ON v_%s."ObjID" = o."ID" AND v_%s."ClassID" = %s',
            v_id, v_id, v_id, v_id
          )
          ELSE ''
        END
      );
    ELSE
      v_parent_view := "Meta".fn_class_view_name(v_parent);
      v_sql := format(
        'CREATE OR REPLACE VIEW "Meta".%I AS
SELECT p.*%s
FROM "Meta".%I p
JOIN "Meta"."Objs" o ON o."ID" = p."ID"
JOIN "Meta"."ClassClosure" cc
  ON cc."DescendantID" = o."ClassID" AND cc."AncestorID" = %s%s',
        v_view,
        CASE WHEN v_field_select IS NOT NULL THEN E',\n  ' || v_field_select ELSE '' END,
        v_parent_view,
        v_id,
        CASE
          WHEN v_field_select IS NOT NULL THEN format(
            E'\nLEFT JOIN "Meta"."ObjValues" v_%s ON v_%s."ObjID" = o."ID" AND v_%s."ClassID" = %s',
            v_id, v_id, v_id, v_id
          )
          ELSE ''
        END
      );
    END IF;

    EXECUTE format('DROP VIEW IF EXISTS "Meta".%I CASCADE', v_view);
    EXECUTE v_sql;
    PERFORM "Meta".sp_meta_publish_class_type(v_id, false);
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_meta_schema_refresh()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_class_id int;
BEGIN
  IF TG_TABLE_NAME = 'Fields' THEN
    v_class_id := COALESCE(NEW."ClassID", OLD."ClassID");
  ELSIF TG_TABLE_NAME = 'Classes' THEN
    v_class_id := COALESCE(NEW."ID", OLD."ID");
  ELSE
    v_class_id := NULL;
  END IF;

  IF v_class_id IS NOT NULL THEN
    PERFORM "Meta".sp_class_regenerate_views(v_class_id);
  END IF;

  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_Fields_SchemaRefresh" ON "Meta"."Fields";
CREATE TRIGGER "TR_Fields_SchemaRefresh"
  AFTER INSERT OR UPDATE OR DELETE
  ON "Meta"."Fields"
  FOR EACH ROW
  EXECUTE FUNCTION "Meta".trg_meta_schema_refresh();

CREATE OR REPLACE FUNCTION "Meta".trg_classes_hierarchy_after()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;

  IF TG_OP = 'UPDATE' AND NEW."ParentID" IS NOT DISTINCT FROM OLD."ParentID" THEN
    RETURN NEW;
  END IF;

  PERFORM "Meta".sp_refresh_class_hierarchy(NEW."ID");
  PERFORM "Meta".sp_class_regenerate_views(NEW."ID");
  RETURN NEW;
END;
$$;
