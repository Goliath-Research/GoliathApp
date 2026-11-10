-- Official platform generic Meta hierarchy (clean baseline). Idempotent; no tenant data.
-- Applied by apply_schema.sh after meta_model_semantic.sql — see docs/platform-generic-meta.md.

BEGIN;

SELECT portal.sp_nav_ensure_meta_catalog();

DO $platform_meta$
DECLARE
  v_string_type bigint;
  v_class_id int;
  v_parent_id int;
  v_names text[] := ARRAY[
    'platform/Entity',
    'platform/Party',
    'platform/Organization',
    'platform/Person',
    'platform/Item',
    'platform/Material',
    'platform/Location',
    'platform/Site',
    'platform/Document',
    'platform/Event',
    'platform/Activity',
    'platform/Batch',
    'platform/Lot',
    'platform/Measurement',
    'platform/Observation'
  ];
  v_parents text[] := ARRAY[
    NULL,
    'platform/Entity',
    'platform/Party',
    'platform/Party',
    'platform/Entity',
    'platform/Item',
    'platform/Entity',
    'platform/Location',
    'platform/Entity',
    'platform/Entity',
    'platform/Event',
    'platform/Entity',
    'platform/Batch',
    'platform/Entity',
    'platform/Measurement'
  ];
  i int;
  p_name text;
  p_parent text;
  v_label_classes text[] := ARRAY[
    'platform/Organization',
    'platform/Person',
    'platform/Material',
    'platform/Site',
    'platform/Document',
    'platform/Activity',
    'platform/Lot',
    'platform/Observation'
  ];
  lc text;
BEGIN
  SELECT t.id INTO v_string_type
  FROM wf.data_type t
  WHERE t.name = 'portal/nav/Caption' AND t.version = '1.0'
  LIMIT 1;

  FOR i IN 1 .. array_length(v_names, 1)
  LOOP
    p_name := v_names[i];
    p_parent := v_parents[i];
    v_parent_id := NULL;
    IF p_parent IS NOT NULL THEN
      SELECT c."ID" INTO v_parent_id FROM "Meta"."Classes" c WHERE c."Name" = p_parent LIMIT 1;
    END IF;
    INSERT INTO "Meta"."Classes" ("Name", "ParentID")
    SELECT p_name, v_parent_id
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = p_name);
  END LOOP;

  PERFORM "Meta".sp_backfill_all_class_hierarchies();

  IF v_string_type IS NOT NULL THEN
    FOREACH lc IN ARRAY v_label_classes
    LOOP
      SELECT c."ID" INTO v_class_id FROM "Meta"."Classes" c WHERE c."Name" = lc LIMIT 1;
      IF v_class_id IS NULL THEN
        CONTINUE;
      END IF;
      INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
      SELECT v_class_id, 'Label', v_string_type, true, 'Human-readable label'
      WHERE NOT EXISTS (
        SELECT 1 FROM "Meta"."Fields" f WHERE f."ClassID" = v_class_id AND f."Name" = 'Label'
      );
    END LOOP;
  END IF;
END
$platform_meta$;

COMMIT;
