-- pgTAP: Meta model inheritance and ObjValues key check (docs/meta-model.md §9)
-- Run: pg_prove -d $PGDATABASE workflow_engine/sql_pg/tap/meta_model_phase_d.tap.sql

BEGIN;
SELECT plan(3);

SELECT has_column('Meta', 'Classes', 'AncestorPath', 'Classes carry AncestorPath');
SELECT has_table('Meta', 'ObjValues', 'ObjValues JSONB storage exists');

SELECT throws_like(
  $$SELECT "Meta".fn_obj_values_key_check(1, 1, '{"unexpected": true}'::jsonb)$$,
  '%unknown field%',
  'unknown keys rejected by fn_obj_values_key_check'
);

SELECT * FROM finish();
ROLLBACK;
