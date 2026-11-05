-- Meta model semantic integration (docs/meta-model.md §7)

DO $fk$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_semantic_entity_meta_class') THEN
    ALTER TABLE portal.semantic_entity
      ADD CONSTRAINT fk_semantic_entity_meta_class
      FOREIGN KEY (meta_class_id) REFERENCES "Meta"."Classes" ("ID");
  END IF;
EXCEPTION
  WHEN others THEN
    RAISE NOTICE 'skip fk_semantic_entity_meta_class: %', SQLERRM;
END
$fk$;

CREATE OR REPLACE FUNCTION "Meta".sp_semantic_sync_class_entity(
  p_class_id int,
  p_namespace text,
  p_entity_code text,
  p_display_name text DEFAULT NULL,
  p_description text DEFAULT NULL
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  v_class record;
  v_view text;
  v_type record;
  v_entity_id int;
BEGIN
  SELECT c."ID", c."Name", c."TypeID", c."Description"
  INTO v_class
  FROM "Meta"."Classes" c
  WHERE c."ID" = p_class_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Meta class % not found', p_class_id;
  END IF;

  IF v_class."TypeID" IS NULL THEN
    PERFORM "Meta".sp_meta_publish_class_type(p_class_id, false);
    SELECT c."TypeID" INTO v_class."TypeID"
    FROM "Meta"."Classes" c WHERE c."ID" = p_class_id;
  END IF;

  PERFORM "Meta".sp_class_regenerate_views(p_class_id);
  v_view := format('"Meta".%I', "Meta".fn_class_view_name(p_class_id));

  SELECT t.name, t.version, t.content_hash, t.schema_json
  INTO v_type
  FROM wf.data_type t
  WHERE t.id = v_class."TypeID";

  CALL portal.sp_semantic_register_entity(
    p_namespace,
    p_entity_code,
    COALESCE(p_display_name, v_class."Name"),
    COALESCE(p_description, v_class."Description", ''),
    "Meta".fn_class_schema_uri(p_class_id),
    v_type.version,
    v_type.content_hash,
    v_view,
    p_class_id
  );

  SELECT e.id INTO v_entity_id
  FROM portal.semantic_entity e
  WHERE e.namespace = p_namespace AND e.code = p_entity_code;

  RETURN v_entity_id;
END;
$$;

CREATE OR REPLACE PROCEDURE wf.wf_repo_bind_action_data_types(
  IN p_action_name text,
  IN p_input_type_name text DEFAULT NULL,
  IN p_input_type_version text DEFAULT NULL,
  IN p_output_type_name text DEFAULT NULL,
  IN p_output_type_version text DEFAULT NULL
)
LANGUAGE plpgsql
AS $$
DECLARE
  v_in bigint;
  v_out bigint;
BEGIN
  IF p_action_name IS NULL OR btrim(p_action_name) = '' THEN
    RETURN;
  END IF;

  IF p_input_type_name IS NOT NULL AND btrim(p_input_type_name) <> '' THEN
    SELECT t.id INTO v_in
    FROM wf.data_type t
    WHERE t.name = p_input_type_name
      AND (p_input_type_version IS NULL OR t.version = p_input_type_version)
    ORDER BY t.id DESC
    LIMIT 1;
  END IF;

  IF p_output_type_name IS NOT NULL AND btrim(p_output_type_name) <> '' THEN
    SELECT t.id INTO v_out
    FROM wf.data_type t
    WHERE t.name = p_output_type_name
      AND (p_output_type_version IS NULL OR t.version = p_output_type_version)
    ORDER BY t.id DESC
    LIMIT 1;
  END IF;

  UPDATE wf.workflow_action a
  SET input_type_id = COALESCE(v_in, a.input_type_id),
      output_type_id = COALESCE(v_out, a.output_type_id)
  WHERE a.action_name = p_action_name;
END;
$$;
