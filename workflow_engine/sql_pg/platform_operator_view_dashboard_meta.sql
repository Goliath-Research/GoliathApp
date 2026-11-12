-- Platform operator view / dashboard Meta classes (Phase V1).
-- Idempotent; applied after platform_generic_meta_baseline.sql.

BEGIN;

SELECT portal.sp_nav_ensure_meta_catalog();

INSERT INTO wf.data_type (name, version, status, kind, schema_json, content_hash)
SELECT v.name, '1.0', 'published', v.kind, v.schema_json, md5(v.schema_json::text)
FROM (VALUES
  ('platform/view/Text', 'string', '{"type":"string","maxLength":2048}'::jsonb),
  ('platform/view/LongText', 'string', '{"type":"string","maxLength":16384}'::jsonb),
  ('platform/view/Integer', 'int', '{"type":"integer"}'::jsonb)
) AS v(name, kind, schema_json)
WHERE NOT EXISTS (
  SELECT 1 FROM wf.data_type t WHERE t.name = v.name AND t.version = '1.0'
);

DO $view_meta$
DECLARE
  v_string bigint;
  v_long bigint;
  v_int bigint;
  v_document int;
  v_entity int;
  v_class int;
BEGIN
  SELECT id INTO v_string FROM wf.data_type WHERE name = 'platform/view/Text' AND version = '1.0';
  SELECT id INTO v_long FROM wf.data_type WHERE name = 'platform/view/LongText' AND version = '1.0';
  SELECT id INTO v_int FROM wf.data_type WHERE name = 'platform/view/Integer' AND version = '1.0';
  SELECT c."ID" INTO v_document FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Document';
  SELECT c."ID" INTO v_entity FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Entity';

  IF v_document IS NULL THEN
    RAISE NOTICE 'platform operator view meta skipped — platform/Document missing';
    RETURN;
  END IF;

  INSERT INTO "Meta"."Classes" ("Name", "ParentID")
  SELECT 'platform/OperatorView', v_document
  WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = 'platform/OperatorView');

  INSERT INTO "Meta"."Classes" ("Name", "ParentID")
  SELECT 'platform/Dashboard', v_document
  WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Dashboard');

  IF v_entity IS NOT NULL THEN
    INSERT INTO "Meta"."Classes" ("Name", "ParentID")
    SELECT 'platform/DashboardWidget', v_entity
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Classes" c WHERE c."Name" = 'platform/DashboardWidget');
  END IF;

  PERFORM "Meta".sp_backfill_all_class_hierarchies();

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/OperatorView';
  IF v_class IS NOT NULL AND v_string IS NOT NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_class, f.name, f.type_id, f.req, f.descr
    FROM (VALUES
      ('Label', v_string, true, 'View title'),
      ('Description', v_long, false, 'View description'),
      ('SourceKind', v_string, true, 'semantic or meta'),
      ('SemanticRequestCode', v_string, false, 'Semantic request code'),
      ('MetaClassName', v_string, false, 'Meta class FQN'),
      ('DefinitionJson', v_long, false, 'Structured definition (columns, filters, viz)'),
      ('Visibility', v_string, true, 'scope | organization | private'),
      ('LegacyViewId', v_int, false, 'portal.operator_view id')
    ) AS f(name, type_id, req, descr)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);
  END IF;

  SELECT c."ID" INTO v_class FROM "Meta"."Classes" c WHERE c."Name" = 'platform/Dashboard';
  IF v_class IS NOT NULL AND v_string IS NOT NULL THEN
    INSERT INTO "Meta"."Fields" ("ClassID", "Name", "TypeID", "Required", "Description")
    SELECT v_class, f.name, f.type_id, f.req, f.descr
    FROM (VALUES
      ('Label', v_string, true, 'Dashboard title'),
      ('Description', v_long, false, 'Dashboard description'),
      ('LayoutJson', v_long, false, 'Grid layout and dashboard-level filters'),
      ('Visibility', v_string, true, 'scope | organization | private'),
      ('LegacyDashboardId', v_int, false, 'portal.operator_dashboard id')
    ) AS f(name, type_id, req, descr)
    WHERE NOT EXISTS (SELECT 1 FROM "Meta"."Fields" x WHERE x."ClassID" = v_class AND x."Name" = f.name);
  END IF;
END
$view_meta$;

CREATE TABLE IF NOT EXISTS portal.operator_view_meta_map (
  legacy_view_id bigint PRIMARY KEY REFERENCES portal.operator_view (id) ON DELETE CASCADE,
  meta_obj_id integer NOT NULL REFERENCES "Meta"."Objs" ("ID") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS portal.operator_dashboard_meta_map (
  legacy_dashboard_id bigint PRIMARY KEY REFERENCES portal.operator_dashboard (id) ON DELETE CASCADE,
  meta_obj_id integer NOT NULL REFERENCES "Meta"."Objs" ("ID") ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_operator_view_meta_map_obj
  ON portal.operator_view_meta_map (meta_obj_id);

CREATE INDEX IF NOT EXISTS ix_operator_dashboard_meta_map_obj
  ON portal.operator_dashboard_meta_map (meta_obj_id);

COMMIT;
