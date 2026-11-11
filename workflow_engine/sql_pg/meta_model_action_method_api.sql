-- Product-neutral: bind a wf.workflow_action to a Meta class method (ImplKind = action).

CREATE OR REPLACE FUNCTION "Meta".sp_meta_upsert_action_method(
  p_class_name text,
  p_method_name text,
  p_action_name text,
  p_description text DEFAULT NULL
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, "Meta", wf, pg_temp
AS $$
DECLARE
  v_class_id integer;
  v_method_id integer;
BEGIN
  IF p_class_name IS NULL OR btrim(p_class_name) = '' THEN
    RAISE EXCEPTION 'class_name is required';
  END IF;
  IF p_method_name IS NULL OR btrim(p_method_name) = '' THEN
    RAISE EXCEPTION 'method_name is required';
  END IF;
  IF p_action_name IS NULL OR btrim(p_action_name) = '' THEN
    RAISE EXCEPTION 'action_name is required';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM wf.workflow_action a WHERE a.action_name = p_action_name) THEN
    RAISE EXCEPTION 'workflow_action % not found', p_action_name;
  END IF;

  SELECT c."ID" INTO v_class_id
  FROM "Meta"."Classes" c
  WHERE c."Name" = p_class_name
  LIMIT 1;
  IF v_class_id IS NULL THEN
    RAISE EXCEPTION 'Meta class % not found', p_class_name;
  END IF;

  SELECT m."ID" INTO v_method_id
  FROM "Meta"."Methods" m
  WHERE m."ClassID" = v_class_id AND m."Name" = p_method_name
  LIMIT 1;

  IF v_method_id IS NULL THEN
    INSERT INTO "Meta"."Methods" ("ClassID", "Name", "Description", "ImplKind", "ImplRef", "IsAbstract")
    VALUES (v_class_id, p_method_name, p_description, 'action', p_action_name, false)
    RETURNING "ID" INTO v_method_id;
  ELSE
    UPDATE "Meta"."Methods" m
    SET "Description" = COALESCE(p_description, m."Description"),
        "ImplKind" = 'action',
        "ImplRef" = p_action_name,
        "IsAbstract" = false
    WHERE m."ID" = v_method_id;
  END IF;

  RETURN v_method_id;
END;
$$;
