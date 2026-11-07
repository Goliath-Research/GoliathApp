-- NavTree → Meta bridge — BACKFILL APPLY (mutating; idempotent)
-- Path: workflow_engine/sql_pg/migrations/20261107_nav_tree_meta_backfill.sql
-- Index: workflow_engine/sql_pg/migrations/README.md
-- Runbook: docs/deploy-nav-tree-migration.md
--
-- Prerequisites: successful apply_schema.sh including portal_nav_meta.sql; backup taken first.
-- Safe re-run: skips portal."NavTree" rows that already have MetaObjID.
--
-- Before this file:
--   migrations/20261107_nav_tree_meta__00_preflight_readonly.sql
--   SELECT * FROM portal.sp_nav_backfill_meta(true);   -- dry-run
-- After this file:
--   migrations/20261107_nav_tree_meta__99_verify_readonly.sql

BEGIN;

SELECT portal.sp_nav_ensure_meta_catalog();

SELECT action, count(*) FROM portal.sp_nav_backfill_meta(false) GROUP BY action ORDER BY action;

COMMIT;
