-- Meta model Phase D (design: docs/meta-model.md §9)
-- Reject unknown top-level document keys in sp_obj_insert/sp_obj_update (parity with SQL trigger).

CREATE OR REPLACE FUNCTION "Meta".fn_reject_unknown_document_keys(
  p_class_id int,
  p_doc jsonb
)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_key text;
BEGIN
  IF p_doc IS NULL THEN
    RETURN;
  END IF;
  FOR v_key IN SELECT jsonb_object_keys(p_doc)
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM "Meta"."VClassFieldsResolved" fr
      WHERE fr."ClassID" = p_class_id AND fr."Name" = v_key
    ) THEN
      RAISE EXCEPTION 'unknown field % in document for class %', v_key, p_class_id;
    END IF;
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

  PERFORM "Meta".fn_reject_unknown_document_keys(p_class_id, COALESCE(p_document, '{}'::jsonb));

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

  PERFORM "Meta".fn_reject_unknown_document_keys(v_class_id, COALESCE(p_document, '{}'::jsonb));

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
