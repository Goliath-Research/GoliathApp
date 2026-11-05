-- Meta model Phase C (design: docs/meta-model.md §4.3–§4.4, §6)
-- Obj insert/update, always-on key validation, optional pg_jsonschema, Tree types.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE "Meta"."Classes"
  ADD COLUMN IF NOT EXISTS "PgValidate" boolean NULL;

CREATE OR REPLACE FUNCTION "Meta".fn_obj_values_key_check(
  p_obj_id int,
  p_class_id int,
  p_data jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  r record;
  v_key text;
BEGIN
  IF p_data IS NULL THEN
    p_data := '{}'::jsonb;
  END IF;

  FOR v_key IN
    SELECT jsonb_object_keys(p_data)
  LOOP
    IF NOT EXISTS (
      SELECT 1
      FROM "Meta"."VClassFieldsResolved" fr
      WHERE fr."ClassID" = p_class_id
        AND fr."DeclaredOnClassID" = p_class_id
        AND fr."Name" = v_key
    ) THEN
      RAISE EXCEPTION 'unknown field % for class level % on object %', v_key, p_class_id, p_obj_id;
    END IF;
  END LOOP;

  FOR r IN
    SELECT fr."Name"
    FROM "Meta"."VClassFieldsResolved" fr
    WHERE fr."ClassID" = p_class_id
      AND fr."DeclaredOnClassID" = p_class_id
      AND fr."Required"
  LOOP
    IF NOT (p_data ? r."Name") OR p_data -> r."Name" = 'null'::jsonb THEN
      RAISE EXCEPTION 'missing required field % for class level % on object %', r."Name", p_class_id, p_obj_id;
    END IF;
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_objvalues_key_check()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM "Meta".fn_obj_values_key_check(NEW."ObjID", NEW."ClassID", NEW."Data");
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS "TR_ObjValues_KeyCheck" ON "Meta"."ObjValues";
CREATE TRIGGER "TR_ObjValues_KeyCheck"
  BEFORE INSERT OR UPDATE OF "Data"
  ON "Meta"."ObjValues"
  FOR EACH ROW
  EXECUTE FUNCTION "Meta".trg_objvalues_key_check();

CREATE OR REPLACE FUNCTION "Meta".fn_merged_obj_document(p_obj_id int)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
  SELECT COALESCE(
    jsonb_object_agg(fr."Name", ov."Data" -> fr."Name")
      FILTER (WHERE ov."Data" ? fr."Name"),
    '{}'::jsonb
  )
  FROM "Meta"."Objs" o
  JOIN "Meta"."ClassClosure" cc ON cc."DescendantID" = o."ClassID"
  JOIN "Meta"."VClassFieldsResolved" fr ON fr."ClassID" = o."ClassID"
  LEFT JOIN "Meta"."ObjValues" ov
    ON ov."ObjID" = o."ID" AND ov."ClassID" = fr."DeclaredOnClassID"
  WHERE o."ID" = p_obj_id;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_class_pg_validate_enabled(p_class_id int)
RETURNS boolean
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_cls boolean;
  v_setting text;
BEGIN
  SELECT c."PgValidate" INTO v_cls FROM "Meta"."Classes" c WHERE c."ID" = p_class_id;
  IF v_cls IS NOT NULL THEN
    RETURN v_cls;
  END IF;
  v_setting := current_setting('goliath.meta_pg_validate', true);
  IF v_setting IS NULL OR btrim(v_setting) = '' THEN
    RETURN false;
  END IF;
  RETURN v_setting::boolean;
EXCEPTION
  WHEN others THEN
    RETURN false;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".fn_class_json_schema_flattened(p_class_id int)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_props jsonb := '{}'::jsonb;
  v_required jsonb := '[]'::jsonb;
  r record;
BEGIN
  FOR r IN
    SELECT fr."Name", fr."TypeID", fr."Required"
    FROM "Meta"."VClassFieldsResolved" fr
    WHERE fr."ClassID" = p_class_id
    ORDER BY fr."Name"
  LOOP
    v_props := v_props || jsonb_build_object(
      r."Name",
      "Meta".fn_effective_type_fragment(r."TypeID")
    );
    IF r."Required" THEN
      v_required := v_required || to_jsonb(r."Name");
    END IF;
  END LOOP;

  RETURN jsonb_build_object(
    '$schema', 'https://json-schema.org/draft/2020-12/schema',
    'type', 'object',
    'properties', v_props,
    'required', v_required,
    'additionalProperties', false
  );
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".trg_objvalues_pg_jsonschema()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_leaf_class int;
  v_doc jsonb;
  v_schema jsonb;
  v_use_allof boolean := true;
BEGIN
  SELECT o."ClassID" INTO v_leaf_class FROM "Meta"."Objs" o WHERE o."ID" = NEW."ObjID";
  IF NOT "Meta".fn_class_pg_validate_enabled(v_leaf_class) THEN
    RETURN NEW;
  END IF;

  v_doc := "Meta".fn_merged_obj_document(NEW."ObjID");

  BEGIN
    v_schema := "Meta".fn_class_json_schema_bundled(v_leaf_class);
    IF extensions.jsonb_matches_schema(v_schema, v_doc) THEN
      RETURN NEW;
    END IF;
  EXCEPTION
    WHEN undefined_function THEN
      v_use_allof := false;
    WHEN others THEN
      v_use_allof := false;
  END;

  IF v_use_allof THEN
    RAISE EXCEPTION 'document failed json schema validation for class %', v_leaf_class;
  END IF;

  IF NOT v_use_allof THEN
    v_schema := "Meta".fn_class_json_schema_flattened(v_leaf_class);
    IF extensions.jsonb_matches_schema(v_schema, v_doc) THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'document failed flattened json schema validation for class %', v_leaf_class;
  END IF;

  RETURN NEW;
END;
$$;

DO $ext$
BEGIN
  CREATE EXTENSION IF NOT EXISTS pg_jsonschema WITH SCHEMA extensions;
EXCEPTION
  WHEN others THEN
    RAISE NOTICE 'pg_jsonschema unavailable: %', SQLERRM;
END
$ext$;

DROP TRIGGER IF EXISTS "TR_ObjValues_PgJsonSchema" ON "Meta"."ObjValues";
DO $trg$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'extensions' AND p.proname = 'jsonb_matches_schema'
  ) THEN
    CREATE TRIGGER "TR_ObjValues_PgJsonSchema"
      BEFORE INSERT OR UPDATE OF "Data"
      ON "Meta"."ObjValues"
      FOR EACH ROW
      EXECUTE FUNCTION "Meta".trg_objvalues_pg_jsonschema();
  END IF;
END
$trg$;

CREATE OR REPLACE FUNCTION "Meta".fn_split_obj_document(p_class_id int, p_doc jsonb)
RETURNS TABLE(class_id int, level_data jsonb)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
  v_lvl int;
  v_level jsonb;
  f record;
BEGIN
  FOR v_lvl IN
    SELECT DISTINCT fr."DeclaredOnClassID"
    FROM "Meta"."VClassFieldsResolved" fr
    WHERE fr."ClassID" = p_class_id
    ORDER BY fr."DeclaredOnClassID"
  LOOP
    v_level := '{}'::jsonb;
    FOR f IN
      SELECT fr."Name"
      FROM "Meta"."VClassFieldsResolved" fr
      WHERE fr."ClassID" = p_class_id
        AND fr."DeclaredOnClassID" = v_lvl
    LOOP
      IF p_doc ? f."Name" THEN
        v_level := v_level || jsonb_build_object(f."Name", p_doc -> f."Name");
      END IF;
    END LOOP;
    class_id := v_lvl;
    level_data := v_level;
    RETURN NEXT;
  END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".sp_obj_insert(
  p_class_id int,
  p_document jsonb
)
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
  v_is_abstract boolean;
  v_obj_id int;
  r record;
BEGIN
  SELECT c."IsAbstract" INTO v_is_abstract FROM "Meta"."Classes" c WHERE c."ID" = p_class_id;
  IF COALESCE(v_is_abstract, false) THEN
    RAISE EXCEPTION 'cannot instantiate abstract class %', p_class_id;
  END IF;

  INSERT INTO "Meta"."Objs" ("ClassID") VALUES (p_class_id) RETURNING "ID" INTO v_obj_id;

  FOR r IN
    SELECT * FROM "Meta".fn_split_obj_document(p_class_id, COALESCE(p_document, '{}'::jsonb))
  LOOP
    PERFORM "Meta".fn_obj_values_key_check(v_obj_id, r.class_id, r.level_data);
    INSERT INTO "Meta"."ObjValues" ("ObjID", "ClassID", "Data")
    VALUES (v_obj_id, r.class_id, r.level_data)
    ON CONFLICT ("ObjID", "ClassID") DO UPDATE SET "Data" = EXCLUDED."Data";
  END LOOP;

  RETURN v_obj_id;
END;
$$;

CREATE OR REPLACE FUNCTION "Meta".sp_obj_update(
  p_obj_id int,
  p_document jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_class_id int;
  r record;
BEGIN
  SELECT o."ClassID" INTO v_class_id FROM "Meta"."Objs" o WHERE o."ID" = p_obj_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'object % not found', p_obj_id;
  END IF;

  FOR r IN
    SELECT * FROM "Meta".fn_split_obj_document(v_class_id, COALESCE(p_document, '{}'::jsonb))
  LOOP
    PERFORM "Meta".fn_obj_values_key_check(p_obj_id, r.class_id, r.level_data);
    INSERT INTO "Meta"."ObjValues" ("ObjID", "ClassID", "Data")
    VALUES (p_obj_id, r.class_id, r.level_data)
    ON CONFLICT ("ObjID", "ClassID") DO UPDATE SET "Data" = EXCLUDED."Data";
  END LOOP;
END;
$$;

-- §6 Tree / TreeRef (ltree-backed hierarchy for hierarchical meta links)

CREATE EXTENSION IF NOT EXISTS ltree;

CREATE TABLE IF NOT EXISTS "Meta"."TreeNodes" (
  "ObjID" int NOT NULL REFERENCES "Meta"."Objs" ("ID") ON DELETE CASCADE,
  "MetaLinkID" int NOT NULL REFERENCES "Meta"."MetaLinks" ("ID") ON DELETE CASCADE,
  "Path" ltree NOT NULL,
  CONSTRAINT "PK_Meta_TreeNodes" PRIMARY KEY ("ObjID", "MetaLinkID")
);

CREATE INDEX IF NOT EXISTS "IX_TreeNodes_Path_gist"
  ON "Meta"."TreeNodes" USING gist ("Path");

INSERT INTO wf.data_type (name, version, status, kind, schema_json, content_hash)
VALUES (
  'meta/Tree',
  '1.0',
  'published',
  'object',
  '{
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "description": "Hierarchical object tree node (ltree path maintained in Meta.TreeNodes)",
    "properties": {
      "objId": { "type": "integer" },
      "metaLinkId": { "type": "integer" }
    },
    "required": ["objId", "metaLinkId"],
    "additionalProperties": false
  }'::jsonb,
  encode(digest('meta/Tree/1.0', 'sha256'), 'hex')
)
ON CONFLICT ON CONSTRAINT uq_wf_data_type_name_version DO UPDATE SET
  schema_json = EXCLUDED.schema_json,
  content_hash = EXCLUDED.content_hash;

INSERT INTO wf.data_type (name, version, status, kind, schema_json, content_hash)
VALUES (
  'meta/TreeRef',
  '1.0',
  'published',
  'object',
  '{
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
      "node": { "type": "integer" },
      "scope": { "type": "string", "enum": ["node", "branch"] }
    },
    "required": ["node", "scope"],
    "additionalProperties": false
  }'::jsonb,
  encode(digest('meta/TreeRef/1.0', 'sha256'), 'hex')
)
ON CONFLICT ON CONSTRAINT uq_wf_data_type_name_version DO UPDATE SET
  schema_json = EXCLUDED.schema_json,
  content_hash = EXCLUDED.content_hash;
