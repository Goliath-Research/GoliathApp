/*
  Platform actions as class methods (data seed).

  Every platform action in the wf.workflow_action catalog (engine, core and inventory namespaces)
  is bound to a Meta class method (ImplKind 'action') whose parameters are typed by catalog data
  types. Child apps add or override methods by seeding their own classes; nothing here is
  product-specific.

  The catalog rows are written by seed_action_catalog.py, which may run before or after this file,
  so the binding lives in "Meta".sp_seed_platform_action_methods() and is called from both places.
  Actions that are not in the catalog yet are skipped. Re-running is idempotent: method rows are
  upserted and parameters are rewritten only when they differ. Catalog input schemas are left as
  published by the action catalog.
*/

BEGIN;

INSERT INTO wf.data_type (name, version, status, kind, schema_json, content_hash)
SELECT v.name, '1.0', 'published', v.kind, v.schema_json, md5(v.schema_json::text)
FROM (VALUES
  ('platform/action/Boolean', 'bool', '{"type":"boolean"}'::jsonb),
  ('platform/action/Integer', 'int', '{"type":"integer"}'::jsonb),
  ('platform/action/Decimal', 'number', '{"type":"number"}'::jsonb),
  ('platform/action/Text', 'string', '{"type":"string","maxLength":4096}'::jsonb),
  ('platform/action/Path', 'string', '{"type":"string","maxLength":4096,"description":"Filesystem path"}'::jsonb),
  ('platform/action/Document', 'object', '{"type":"object","description":"Structured value bound from a workflow variable or step output"}'::jsonb),
  ('platform/action/DocumentList', 'array', '{"type":"array","items":{"type":"object"},"description":"List bound from a workflow variable or step output"}'::jsonb)
) AS v(name, kind, schema_json)
WHERE NOT EXISTS (
  SELECT 1 FROM wf.data_type t WHERE t.name = v.name AND t.version = '1.0'
);

SET LOCAL client_min_messages = warning;

DO $wf_class$
DECLARE
  v_inserted integer;
BEGIN
  INSERT INTO "Meta"."Classes" ("Name", "ParentID", "IsAbstract")
  SELECT 'platform/Workflow', c."ID", true
  FROM "Meta"."Classes" c
  WHERE c."Name" = 'platform/Entity'
    AND NOT EXISTS (SELECT 1 FROM "Meta"."Classes" x WHERE x."Name" = 'platform/Workflow');
  GET DIAGNOSTICS v_inserted = ROW_COUNT;
  IF v_inserted > 0 THEN
    PERFORM "Meta".sp_backfill_all_class_hierarchies();
  END IF;
END;
$wf_class$;

CREATE OR REPLACE FUNCTION "Meta".sp_seed_platform_action_methods()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, "Meta", wf, pg_temp
AS $$
DECLARE
  v_count integer := 0;
  v_spec record;
  v_method_id integer;
  v_params jsonb;
  v_current jsonb;
  v_desc text;
  p jsonb;
  v_ord integer;
BEGIN
  FOR v_spec IN
    SELECT *
    FROM (VALUES
      ('platform/Workflow', 'const_bool', 'workflow.const_bool',
       '[{"name":"value","type":"platform/action/Boolean"}]'),
      ('platform/Workflow', 'const_int', 'workflow.const_int',
       '[{"name":"value","type":"platform/action/Integer"}]'),
      ('platform/Workflow', 'const_string', 'workflow.const_string',
       '[{"name":"value","type":"platform/action/Text"}]'),
      ('platform/Workflow', 'const_path', 'workflow.const_path',
       '[{"name":"value","type":"platform/action/Path"}]'),
      ('platform/Workflow', 'json_path_bool', 'workflow.json_path_bool',
       '[{"name":"document","type":"platform/action/Document","required":false},{"name":"jsonPath","type":"platform/action/Text"}]'),
      ('platform/Workflow', 'json_path_int', 'workflow.json_path_int',
       '[{"name":"document","type":"platform/action/Document","required":false},{"name":"jsonPath","type":"platform/action/Text"}]'),
      ('platform/Workflow', 'json_path_string', 'workflow.json_path_string',
       '[{"name":"document","type":"platform/action/Document","required":false},{"name":"jsonPath","type":"platform/action/Text"}]'),
      ('platform/Workflow', 'fs_stat', 'workflow.fs_stat',
       '[{"name":"path","type":"platform/action/Path"},{"name":"check","type":"platform/action/Text","required":false,"default":"exists"}]'),
      ('platform/Workflow', 'device_adapter_command', 'workflow.device_adapter.command',
       '[{"name":"command_key","type":"platform/action/Text"},{"name":"arguments","type":"platform/action/Document","required":false},{"name":"idempotency_key","type":"platform/action/Text"},{"name":"correlation_key","type":"platform/action/Text","required":false,"default":""},{"name":"timeout_seconds","type":"platform/action/Decimal","required":false,"default":30},{"name":"target","type":"platform/action/Document","required":false}]'),
      ('platform/Workflow', 'device_adapter_observe', 'workflow.device_adapter.observe',
       '[{"name":"observe_key","type":"platform/action/Text","required":false,"default":""},{"name":"context","type":"platform/action/Document","required":false}]'),
      ('platform/Activity', 'plan_iterations', 'validation.plan_iterations',
       '[{"name":"projectPath","type":"platform/action/Path"},{"name":"featureIterations","type":"platform/action/Integer","required":false},{"name":"qualityIterations","type":"platform/action/Integer","required":false},{"name":"seed","type":"platform/action/Integer","required":false},{"name":"trainFraction","type":"platform/action/Decimal","required":false},{"name":"layout","type":"platform/action/Text","required":false},{"name":"iterations","type":"platform/action/DocumentList","required":false}]'),
      ('platform/Lot', 'receive_stock', 'inv.stock.receive',
       '[{"name":"organization_id","type":"platform/action/Integer"},{"name":"user_id","type":"platform/action/Integer"},{"name":"po_line_id","type":"platform/action/Integer"},{"name":"bin_id","type":"platform/action/Integer"},{"name":"qty","type":"platform/action/Decimal"},{"name":"lot_number","type":"platform/action/Text","required":false},{"name":"unit_price_override","type":"platform/action/Decimal","required":false}]'),
      ('platform/Lot', 'adjust_stock', 'inv.stock.adjust',
       '[{"name":"organization_id","type":"platform/action/Integer"},{"name":"user_id","type":"platform/action/Integer"},{"name":"stock_lot_id","type":"platform/action/Integer"},{"name":"qty_delta","type":"platform/action/Decimal"},{"name":"reason_code","type":"platform/action/Text"}]'),
      ('platform/Lot', 'issue_stock', 'inv.stock.issue',
       '[{"name":"organization_id","type":"platform/action/Integer"},{"name":"user_id","type":"platform/action/Integer"},{"name":"stock_lot_id","type":"platform/action/Integer"},{"name":"qty","type":"platform/action/Decimal"},{"name":"ref_type","type":"platform/action/Text"},{"name":"ref_id","type":"platform/action/Text"}]')
    ) AS t(class_name, method_name, action_name, params)
  LOOP
    CONTINUE WHEN NOT EXISTS (SELECT 1 FROM wf.workflow_action a WHERE a.action_name = v_spec.action_name);
    CONTINUE WHEN NOT EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = v_spec.class_name);

    SELECT a.display_name::text INTO v_desc
    FROM wf.workflow_action a WHERE a.action_name = v_spec.action_name LIMIT 1;

    v_method_id := "Meta".sp_meta_upsert_action_method(
      v_spec.class_name, v_spec.method_name, v_spec.action_name, v_desc
    );

    -- Desired parameter rows (ordinal, name, type id, required, default).
    v_params := '[]'::jsonb;
    v_ord := 0;
    FOR p IN SELECT * FROM jsonb_array_elements(v_spec.params::jsonb)
    LOOP
      v_ord := v_ord + 1;
      v_params := v_params || jsonb_build_array(jsonb_build_object(
        'ord', v_ord,
        'name', p->>'name',
        'type', (SELECT t.id FROM wf.data_type t WHERE t.name = p->>'type' AND t.version = '1.0'),
        'req', COALESCE((p->>'required')::boolean, true),
        'def', p->'default'
      ));
    END LOOP;

    SELECT COALESCE(jsonb_agg(jsonb_build_object(
             'ord', mp."Ordinal", 'name', mp."Name", 'type', mp."TypeID",
             'req', mp."Required", 'def', mp."DefaultValue") ORDER BY mp."Ordinal"), '[]'::jsonb)
    INTO v_current
    FROM "Meta"."MethodParams" mp
    WHERE mp."MethodID" = v_method_id;

    IF v_current IS DISTINCT FROM v_params THEN
      DELETE FROM "Meta"."MethodParams" mp WHERE mp."MethodID" = v_method_id;
      INSERT INTO "Meta"."MethodParams" ("MethodID", "Ordinal", "Name", "TypeID", "Required", "DefaultValue")
      SELECT v_method_id, (e->>'ord')::int, e->>'name', (e->>'type')::bigint, (e->>'req')::boolean,
             CASE WHEN e ? 'def' AND jsonb_typeof(e->'def') <> 'null' THEN e->'def' END
      FROM jsonb_array_elements(v_params) e;
    END IF;

    v_count := v_count + 1;
  END LOOP;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION "Meta".sp_seed_platform_action_methods() FROM PUBLIC;

SELECT "Meta".sp_seed_platform_action_methods();

COMMIT;
